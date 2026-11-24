import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.attachments import (
    AttachmentError,
    delete_attachment,
    find_attachment_file,
    list_attachments,
    save_attachment,
)
from core.config import settings
from core.db import SessionLocal
from core.git_client import (
    GitClientError,
    commit_subtask_instruction,
    create_worktree,
    push_branch,
    slugify,
)
from core.github_client import (
    GitHubClientError,
    close_pr,
    create_draft_pr,
    edit_pr_body,
    edit_pr_title,
    get_issue,
    get_pr_state,
    reopen_pr,
)
from core.job_queue import ExecutionJobStatus
from core.lifecycle import LifecycleState
from core.models import ExecutionJob, Project, Subtask
from core.mr_naming import compose_mr_title, next_default_suffix
from core.merge_queue import enqueue_merge, find_active_merge
from core.pr_sync import lifecycle_state_from_pr
from core.subtask_rollback import (
    SubtaskCreationStage,
    describe_rollback_result,
    rollback_subtask_creation,
)

router = APIRouter(prefix="/api/subtasks")

logger = logging.getLogger(__name__)

# Issue作成と並行して作るMRのブランチ名の接頭辞（Issue番号の代わりに一意な識別子を続ける）
PENDING_BRANCH_PREFIX = "issue-new"
# ブランチ名に含める一意な識別子の長さ
UNIQUE_BRANCH_ID_LENGTH = 8
# Issue紐付け前のPR本文
PENDING_PR_BODY = "Issue紐付け待ち"
DEFAULT_BRANCH_SLUG = "subtask"


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


def _resolve_issue_title(project: Project, payload: CreateSubtaskRequest) -> str:
    """MR名に使うIssue名

    指定があればGitHubへの問い合わせを省略する。
    """
    return payload.issue_title.strip() or get_issue(
        project.github_repo, payload.github_issue_number
    )["title"]


def _create_branch_and_draft_pr(
    project: Project,
    issue_number: int,
    title: str,
    instruction: str,
    slug_suffix: int,
    slug_source: str | None = None,
    unique_branch: bool = False,
) -> tuple[str, dict]:
    if unique_branch:
        branch_name = _unique_branch_name(f"issue-{issue_number}")
    else:
        slug = slugify(slug_source or title) or DEFAULT_BRANCH_SLUG
        branch_name = f"issue-{issue_number}-{slug}-{slug_suffix}"
    pr = _push_draft_pr(project, branch_name, title, instruction, _related_issue_body(issue_number))
    return branch_name, pr


def _related_issue_body(issue_number: int) -> str:
    return f"Related to #{issue_number}"


def _push_draft_pr(project: Project, branch_name: str, title: str, instruction: str, body: str) -> dict:
    """worktreeを作成して指示を記録し、Draft PRを作成する

    途中で失敗した場合、完了した段階を取り消してから例外を投げ直す。
    後始末で残ったものは例外のメッセージに含める。
    """
    worktree_path = f"{settings.worktree_base_dir}/{branch_name}"
    completed: set[SubtaskCreationStage] = set()
    try:
        _run_creation_stages(project, branch_name, title, instruction, worktree_path, completed)
        return create_draft_pr(
            repo=project.github_repo,
            base=project.default_branch,
            head=branch_name,
            title=title,
            body=body,
        )
    except (GitClientError, GitHubClientError) as exc:
        if not completed:
            raise
        leftovers = rollback_subtask_creation(project.repo_path, worktree_path, branch_name, completed)
        raise type(exc)(f"{exc}\n{describe_rollback_result(leftovers)}") from exc


def _run_creation_stages(
    project: Project,
    branch_name: str,
    title: str,
    instruction: str,
    worktree_path: str,
    completed: set[SubtaskCreationStage],
) -> None:
    """Draft PR作成前の段階を実行し、完了した段階をcompletedに記録する"""
    create_worktree(project.repo_path, branch_name, project.default_branch, worktree_path)
    completed.add(SubtaskCreationStage.WORKTREE_CREATED)
    commit_subtask_instruction(worktree_path, title, instruction)
    completed.add(SubtaskCreationStage.INSTRUCTION_COMMITTED)
    push_branch(worktree_path, branch_name)
    completed.add(SubtaskCreationStage.BRANCH_PUSHED)


def _find_or_add_subtask(session, project_id: int, issue_number: int, branch_name: str) -> Subtask:
    """作成したPRのサブタスク行を返す

    PR作成直後に自動同期が管理塔外のPRとして取り込んでいる場合、その行を使う。
    """
    keys = {"project_id": project_id, "github_issue_number": issue_number, "branch_name": branch_name}
    subtask = session.query(Subtask).filter_by(**keys).first()
    if subtask is None:
        subtask = Subtask(**keys)
        session.add(subtask)
    return subtask


@router.post("")
def create_subtask(payload: CreateSubtaskRequest):
    with SessionLocal() as session:
        project = _get_project_or_404(session, payload.project_id)

        existing_titles = [
            s.title
            for s in session.query(Subtask).filter_by(
                project_id=project.id,
                github_issue_number=payload.github_issue_number,
            )
        ]

        try:
            issue_title = _resolve_issue_title(project, payload)
            suffix = payload.title.strip() or next_default_suffix(issue_title, existing_titles)
            title = compose_mr_title(issue_title, suffix)
            branch_name, pr = _create_branch_and_draft_pr(
                project,
                payload.github_issue_number,
                title,
                payload.instruction,
                len(existing_titles) + 1,
                slug_source=suffix,
                unique_branch=payload.unique_branch,
            )
        except (GitClientError, GitHubClientError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        subtask = _find_or_add_subtask(
            session, project.id, payload.github_issue_number, branch_name
        )
        _apply_created_pr(subtask, title, payload.instruction, pr["number"])
        session.commit()
        return _created_subtask_response(subtask, pr["url"])


def _apply_created_pr(subtask: Subtask, title: str, instruction: str, pr_number: int) -> None:
    subtask.title = title
    subtask.instruction = instruction
    subtask.github_pr_number = pr_number
    subtask.lifecycle_state = LifecycleState.DRAFT


def _created_subtask_response(subtask: Subtask, pr_url: str) -> dict:
    return {
        "id": subtask.id,
        "title": subtask.title,
        "branch_name": subtask.branch_name,
        "github_pr_number": subtask.github_pr_number,
        "pr_url": pr_url,
        "lifecycle_state": subtask.lifecycle_state,
    }


class CreatePendingSubtaskRequest(BaseModel):
    project_id: int
    # 並行して作成中のIssue名
    issue_title: str


@router.post("/pending")
def create_pending_subtask(payload: CreatePendingSubtaskRequest):
    """Issue作成と並行して、Issue未紐付けの規定値MRを作成する

    Issue番号が未確定のため、ブランチ名はIssue番号の代わりに一意な識別子を使う。
    DBへの登録とIssueの紐付けは、Issue作成後にlinkで行う。
    """
    issue_title = payload.issue_title.strip()
    if not issue_title:
        raise HTTPException(status_code=400, detail="issue_title is empty")
    with SessionLocal() as session:
        project = _get_project_or_404(session, payload.project_id)
    title = compose_mr_title(issue_title, next_default_suffix(issue_title, []))
    branch_name = _unique_branch_name(PENDING_BRANCH_PREFIX)
    try:
        pr = _push_draft_pr(project, branch_name, title, "", PENDING_PR_BODY)
    except (GitClientError, GitHubClientError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "title": title,
        "branch_name": branch_name,
        "github_pr_number": pr["number"],
        "pr_url": pr["url"],
    }


def _unique_branch_name(head: str) -> str:
    """一意な識別子を含むブランチ名

    先頭部分（issue-{Issue番号}またはissue-new）の後ろに識別子を続ける。
    """
    unique_id = uuid4().hex[:UNIQUE_BRANCH_ID_LENGTH]
    return f"{head}-{unique_id}-{DEFAULT_BRANCH_SLUG}-1"


def _get_project_or_404(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


class LinkPendingSubtaskRequest(BaseModel):
    project_id: int
    github_issue_number: int
    title: str
    branch_name: str
    github_pr_number: int
    pr_url: str = ""


@router.post("/pending/link")
def link_pending_subtask(payload: LinkPendingSubtaskRequest, background_tasks: BackgroundTasks):
    """Issue作成と並行して作成したMRをIssueに紐付けてDBへ登録する

    PR本文へのIssue番号の記載は、応答を待たせないよう応答後に行う。
    """
    if not payload.branch_name.startswith(f"{PENDING_BRANCH_PREFIX}-"):
        raise HTTPException(status_code=400, detail="Issue未紐付けのMRではありません")
    with SessionLocal() as session:
        project = _get_project_or_404(session, payload.project_id)
        subtask = _find_or_add_subtask(
            session, project.id, payload.github_issue_number, payload.branch_name
        )
        _apply_created_pr(subtask, payload.title, "", payload.github_pr_number)
        session.commit()
        background_tasks.add_task(
            _link_pr_to_issue,
            project.github_repo,
            payload.github_pr_number,
            payload.github_issue_number,
        )
        return _created_subtask_response(subtask, payload.pr_url)


def _link_pr_to_issue(repo: str, pr_number: int, issue_number: int) -> None:
    """PR本文にIssue番号を記載する

    管理塔上の紐付けはDB登録済のため、失敗はログ出力のみとする。
    """
    try:
        edit_pr_body(repo, pr_number, _related_issue_body(issue_number))
    except GitHubClientError as exc:
        logger.warning("PR #%s のIssue #%s 紐付けに失敗しました: %s", pr_number, issue_number, exc)


class DiscardPendingSubtaskRequest(BaseModel):
    project_id: int
    github_pr_number: int


@router.post("/pending/discard")
def discard_pending_subtask(payload: DiscardPendingSubtaskRequest):
    """Issue作成に失敗した場合に、並行して作成したMRをクローズする

    worktree・ブランチは残す。
    """
    with SessionLocal() as session:
        project = _get_project_or_404(session, payload.project_id)
    try:
        close_pr(project.github_repo, payload.github_pr_number)
    except GitHubClientError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"github_pr_number": payload.github_pr_number}


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
        raise HTTPException(status_code=400, detail="title is empty")
    with SessionLocal() as session:
        subtask, project = _get_subtask_and_project(session, subtask_id)

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


def _get_subtask_or_404(session, subtask_id: int) -> Subtask:
    subtask = session.get(Subtask, subtask_id)
    if subtask is None:
        raise HTTPException(status_code=404, detail="subtask not found")
    return subtask


def _get_subtask_and_project(session, subtask_id: int) -> tuple[Subtask, Project]:
    subtask = _get_subtask_or_404(session, subtask_id)
    return subtask, session.get(Project, subtask.project_id)


@router.post("/{subtask_id}/close")
def close_subtask(subtask_id: int):
    """MRをクローズする

    マージ済のMRは閉じられないため拒否する。
    """
    with SessionLocal() as session:
        subtask, project = _get_subtask_and_project(session, subtask_id)
        if subtask.lifecycle_state not in LifecycleState.OPEN_STATES:
            raise HTTPException(status_code=409, detail="未解決のMRではありません")
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
        subtask, project = _get_subtask_and_project(session, subtask_id)
        if subtask.lifecycle_state != LifecycleState.CANCELED:
            raise HTTPException(status_code=409, detail="クローズ済のMRではありません")
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
        raise HTTPException(status_code=409, detail="ResolvedのMRではありません")
    if subtask.github_pr_number is None:
        raise HTTPException(status_code=409, detail="PRが作成されていません")
    if _has_active_job(session, subtask.id):
        raise HTTPException(status_code=409, detail="実装の実行中はマージできません")


@router.post("/{subtask_id}/merge")
def merge_subtask(subtask_id: int):
    """MRをマージ待ち行列に登録する

    Resolvedかつ実装の実行中・マージ待ちでない場合のみ受け付ける。
    マージは待ち行列から1件ずつ順に行う。
    競合時はベースブランチを取り込み、Claudeで競合解決してからマージする。
    """
    with SessionLocal() as session:
        subtask, _ = _get_subtask_and_project(session, subtask_id)
        _ensure_mergeable(session, subtask)
        if find_active_merge(session, subtask.id) is not None:
            raise HTTPException(status_code=409, detail="マージ待ちに登録済です")
        job = enqueue_merge(session, subtask.id)
        return {
            "id": subtask.id,
            "lifecycle_state": subtask.lifecycle_state,
            "latest_merge": {"id": job.id, "status": job.status, "error_message": None},
        }


def _subtask_worktree_path(subtask_id: int) -> str:
    with SessionLocal() as session:
        subtask = _get_subtask_or_404(session, subtask_id)
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
        raise HTTPException(status_code=404, detail="attachment not found")
    return FileResponse(path)


@router.post("/{subtask_id}/attachments")
async def upload_attachment(subtask_id: int, file: UploadFile):
    """実装指示の添付ファイルを保存する

    IDはS1、S2…の連番で割り当てる。
    """
    worktree_path = _subtask_worktree_path(subtask_id)
    if not Path(worktree_path).is_dir():
        raise HTTPException(status_code=409, detail="worktreeがありません")
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
        raise HTTPException(status_code=404, detail="attachment not found")
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
        detail={"message": "実装の実行中・実行待ちです", "job_id": job.id, "status": job.status},
    )


@router.post("/{subtask_id}/execute")
def execute_subtask(subtask_id: int, payload: ExecuteSubtaskRequest | None = None):
    """実装ジョブを登録する

    マージ待ち、または実装ジョブの待機中・実行中は409を返す。
    """
    with SessionLocal() as session:
        subtask = _get_subtask_or_404(session, subtask_id)

        if find_active_merge(session, subtask_id) is not None:
            raise HTTPException(status_code=409, detail="マージ待ちのMRは実装できません")
        _ensure_no_active_job(session, subtask_id)

        if payload is not None and payload.instruction:
            subtask.instruction = payload.instruction

        job = ExecutionJob(subtask_id=subtask_id, status=ExecutionJobStatus.QUEUED)
        session.add(job)
        session.commit()
        session.refresh(job)

        return {"job_id": job.id, "status": job.status}
