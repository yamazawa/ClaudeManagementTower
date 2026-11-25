from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.routes import error_messages as messages
from app.routes.lookups import get_project_or_404, get_subtask_and_project_or_404, get_subtask_or_404
from core.attachments import (
    AttachmentError,
    delete_attachment,
    find_attachment_file,
    list_attachments,
    save_attachment,
)
from core.config import settings
from core.db import SessionLocal
from core.github_client import (
    GitHubClientError,
    close_pr,
    edit_pr_title,
    get_issue,
    get_pr_state,
    reopen_pr,
)
from core.issue_mr_creation import CREATION_ERRORS, create_mr
from core.job_queue import ExecutionJobStatus
from core.lifecycle import LifecycleState
from core.models import ExecutionJob, Project, Subtask
from core.mr_naming import compose_mr_title
from core.merge_queue import enqueue_merge, find_active_merge
from core.pr_sync import lifecycle_state_from_pr

router = APIRouter(prefix="/api/subtasks")


class CreateSubtaskRequest(BaseModel):
    project_id: int
    github_issue_number: int
    # MR固有名（MR名のIssue名より後ろの部分）。空欄なら連番を割り当てる
    title: str = ""
    instruction: str = ""
    # Issue名。Issue作成直後など呼び出し側で既知の場合に指定する。空欄ならGitHubから取得する
    issue_title: str = ""
    # ブランチ名に連番の代わりに一意な識別子を使うか（作成失敗後の再作成でも重複させない）
    unique_branch: bool = False


@router.post("")
def create_subtask(payload: CreateSubtaskRequest):
    """既存IssueにMRを作成する

    作成処理は画面・アイデアマン・CLIタブで共通の処理を使う。
    """
    with SessionLocal() as session:
        project = get_project_or_404(session, payload.project_id)
    try:
        return create_mr(
            project,
            payload.github_issue_number,
            suffix=payload.title,
            instruction=payload.instruction,
            issue_title=payload.issue_title,
            unique_branch=payload.unique_branch,
            session_factory=SessionLocal,
        )
    except CREATION_ERRORS as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class UpdateSubtaskTitleRequest(BaseModel):
    # MR固有名（MR名のIssue名より後ろの部分）
    title: str


@router.patch("/{subtask_id}")
def update_subtask_title(subtask_id: int, payload: UpdateSubtaskTitleRequest):
    """MR名のMR固有名部分を変更する

    Issue名は最新のものをGitHubから取得して付け直す。
    """
    suffix = payload.title.strip()
    if not suffix:
        raise HTTPException(status_code=400, detail=messages.TITLE_EMPTY)
    with SessionLocal() as session:
        subtask, project = get_subtask_and_project_or_404(session, subtask_id)

        try:
            issue_title = get_issue(project.github_repo, subtask.github_issue_number)["title"]
            title = compose_mr_title(issue_title, suffix)
            if subtask.github_pr_number is not None:
                edit_pr_title(project.github_repo, subtask.github_pr_number, title)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        subtask.title = title
        session.commit()
        return {"id": subtask.id, "title": subtask.title}


@router.post("/{subtask_id}/close")
def close_subtask(subtask_id: int):
    """MRをクローズする

    マージ済のMRは閉じられないため拒否する。
    """
    with SessionLocal() as session:
        subtask, project = get_subtask_and_project_or_404(session, subtask_id)
        if subtask.lifecycle_state not in LifecycleState.OPEN_STATES:
            raise HTTPException(status_code=409, detail=messages.NOT_UNRESOLVED_MR)
        try:
            if subtask.github_pr_number is not None:
                close_pr(project.github_repo, subtask.github_pr_number)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        subtask.lifecycle_state = LifecycleState.CANCELED
        session.commit()
        return {"id": subtask.id, "lifecycle_state": subtask.lifecycle_state}


def _reopen_pr_and_get_state(project: Project, pr_number: int | None) -> str:
    if pr_number is None:
        return LifecycleState.DRAFT
    reopen_pr(project.github_repo, pr_number)
    return lifecycle_state_from_pr(get_pr_state(project.github_repo, pr_number))


@router.post("/{subtask_id}/reopen")
def reopen_subtask(subtask_id: int):
    """クローズ済のMRを再開する

    再開後の状態はPRのDraft有無から決める。
    """
    with SessionLocal() as session:
        subtask, project = get_subtask_and_project_or_404(session, subtask_id)
        if subtask.lifecycle_state != LifecycleState.CANCELED:
            raise HTTPException(status_code=409, detail=messages.NOT_CLOSED_MR)
        try:
            new_state = _reopen_pr_and_get_state(project, subtask.github_pr_number)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        subtask.lifecycle_state = new_state
        session.commit()
        return {"id": subtask.id, "lifecycle_state": subtask.lifecycle_state}


def _find_active_job(session, subtask_id: int) -> ExecutionJob | None:
    return (
        session.query(ExecutionJob)
        .filter_by(subtask_id=subtask_id)
        .filter(ExecutionJob.status.in_(ExecutionJobStatus.ACTIVE_STATES))
        .order_by(ExecutionJob.id)
        .first()
    )


def _has_active_job(session, subtask_id: int) -> bool:
    return _find_active_job(session, subtask_id) is not None


def _ensure_mergeable(session, subtask: Subtask) -> None:
    if subtask.lifecycle_state != LifecycleState.RESOLVED:
        raise HTTPException(status_code=409, detail=messages.NOT_RESOLVED_MR)
    if subtask.github_pr_number is None:
        raise HTTPException(status_code=409, detail=messages.PR_NOT_CREATED)
    if _has_active_job(session, subtask.id):
        raise HTTPException(status_code=409, detail=messages.MERGE_BLOCKED_BY_ACTIVE_JOB)


@router.post("/{subtask_id}/merge")
def merge_subtask(subtask_id: int):
    """MRをマージ待ち行列に登録する

    Resolvedかつ実装の実行中・マージ待ちでない場合のみ受け付ける。
    マージは待ち行列から1件ずつ順に行う。
    競合時はベースブランチを取り込み、Claudeで競合解決してからマージする。
    """
    with SessionLocal() as session:
        subtask, _ = get_subtask_and_project_or_404(session, subtask_id)
        _ensure_mergeable(session, subtask)
        if find_active_merge(session, subtask.id) is not None:
            raise HTTPException(status_code=409, detail=messages.ALREADY_IN_MERGE_QUEUE)
        job = enqueue_merge(session, subtask.id)
        return {
            "id": subtask.id,
            "lifecycle_state": subtask.lifecycle_state,
            "latest_merge": {"id": job.id, "status": job.status, "error_message": None},
        }


def _subtask_worktree_path(subtask_id: int) -> str:
    with SessionLocal() as session:
        subtask = get_subtask_or_404(session, subtask_id)
        return f"{settings.worktree_base_dir}/{subtask.branch_name}"


@router.get("/{subtask_id}/attachments")
def get_attachments(subtask_id: int):
    return list_attachments(_subtask_worktree_path(subtask_id))


@router.get("/{subtask_id}/attachments/{attachment_id}/file")
def get_attachment_file(subtask_id: int, attachment_id: str):
    """添付ファイルの内容を返す

    画像添付のサムネイル表示に使う。
    """
    path = find_attachment_file(_subtask_worktree_path(subtask_id), attachment_id)
    if path is None:
        raise HTTPException(status_code=404, detail=messages.ATTACHMENT_NOT_FOUND)
    return FileResponse(path)


@router.post("/{subtask_id}/attachments")
async def upload_attachment(subtask_id: int, file: UploadFile):
    """実装指示の添付ファイルを保存する

    IDはS1、S2…の連番で割り当てる。
    """
    worktree_path = _subtask_worktree_path(subtask_id)
    if not Path(worktree_path).is_dir():
        raise HTTPException(status_code=409, detail=messages.WORKTREE_MISSING)
    try:
        return save_attachment(worktree_path, file.filename or "", await file.read())
    except AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{subtask_id}/attachments/{attachment_id}")
def remove_attachment(subtask_id: int, attachment_id: str):
    """実装指示の添付ファイルを削除する

    残りの添付のIDは振り直さない。
    """
    if not delete_attachment(_subtask_worktree_path(subtask_id), attachment_id):
        raise HTTPException(status_code=404, detail=messages.ATTACHMENT_NOT_FOUND)
    return {"id": attachment_id}


class ExecuteSubtaskRequest(BaseModel):
    instruction: str | None = None


def _ensure_no_active_job(session, subtask_id: int) -> None:
    """実装ジョブの待機中・実行中は実行を拒否する

    画面側が既存ジョブの監視に切り替えられるよう、ジョブIDと状態を返す。
    """
    job = _find_active_job(session, subtask_id)
    if job is None:
        return
    raise HTTPException(
        status_code=409,
        detail={"message": messages.JOB_ACTIVE, "job_id": job.id, "status": job.status},
    )


@router.post("/{subtask_id}/execute")
def execute_subtask(subtask_id: int, payload: ExecuteSubtaskRequest | None = None):
    """実装ジョブを登録する

    マージ待ち、または実装ジョブの待機中・実行中は409を返す。
    """
    with SessionLocal() as session:
        subtask = get_subtask_or_404(session, subtask_id)

        if find_active_merge(session, subtask_id) is not None:
            raise HTTPException(status_code=409, detail=messages.EXECUTE_BLOCKED_BY_MERGE_QUEUE)
        _ensure_no_active_job(session, subtask_id)

        if payload is not None and payload.instruction:
            subtask.instruction = payload.instruction

        job = ExecutionJob(subtask_id=subtask_id, status=ExecutionJobStatus.QUEUED)
        session.add(job)
        session.commit()
        session.refresh(job)

        return {"job_id": job.id, "status": job.status}
