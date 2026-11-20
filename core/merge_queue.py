"""MRのマージ待ち行列

複数ブランチの同時マージによる競合の連鎖を避けるため、マージは1件ずつ順に処理する。
待ち行列はDBに保持し、処理はサーバー内の単一スレッドで行う。
"""

import logging
import threading
from datetime import datetime, timezone

from core.config import settings
from core.db import SessionLocal
from core.lifecycle import LifecycleState
from core.models import MergeJob, Project, Subtask
from core.pr_merger import merge_pr_with_update

logger = logging.getLogger(__name__)


class MergeJobStatus:
    """マージ待ち行列の状態

    QUEUED : マージ待ち
    RUNNING : マージ中
    SUCCEEDED : マージ済
    FAILED : マージ失敗
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    # 待ち行列に残っている状態（同じMRを重ねて登録させない）
    ACTIVE_STATES = (QUEUED, RUNNING)


# 待ち行列が空の場合に新規登録を確認する間隔（登録時は即時に起こす）
MERGE_POLL_INTERVAL_SECONDS = 5
INTERRUPTED_MESSAGE = "サーバー再起動によりマージが中断されました"

_wake_event = threading.Event()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def find_active_merge(session, subtask_id: int) -> MergeJob | None:
    return (
        session.query(MergeJob)
        .filter_by(subtask_id=subtask_id)
        .filter(MergeJob.status.in_(MergeJobStatus.ACTIVE_STATES))
        .first()
    )


def latest_merge_summary(session, subtask_id: int) -> dict | None:
    job = (
        session.query(MergeJob)
        .filter_by(subtask_id=subtask_id)
        .order_by(MergeJob.id.desc())
        .first()
    )
    if job is None:
        return None
    return {"id": job.id, "status": job.status, "error_message": job.error_message}


def enqueue_merge(session, subtask_id: int) -> MergeJob:
    """マージ待ち行列に登録し、処理スレッドを起こす"""
    job = MergeJob(subtask_id=subtask_id, status=MergeJobStatus.QUEUED)
    session.add(job)
    session.commit()
    session.refresh(job)
    _wake_event.set()
    return job


def list_active_merges(session) -> list[dict]:
    """ヘッダー表示用に、マージ中・マージ待ちのMRを処理順に返す"""
    rows = (
        session.query(MergeJob, Subtask)
        .join(Subtask, MergeJob.subtask_id == Subtask.id)
        .filter(MergeJob.status.in_(MergeJobStatus.ACTIVE_STATES))
        .order_by(MergeJob.id)
        .all()
    )
    return [
        {
            "id": job.id,
            "status": job.status,
            "subtask_id": subtask.id,
            "github_issue_number": subtask.github_issue_number,
            "github_pr_number": subtask.github_pr_number,
            "title": subtask.title,
        }
        for job, subtask in rows
    ]


def recover_interrupted_merges(session_factory=None) -> None:
    """起動時に、前回起動中にマージ中だったジョブを失敗扱いにする

    途中まで進んだマージを自動で再開すると状況が追えないため、再登録は利用者に委ねる。
    """
    factory = session_factory or SessionLocal
    with factory() as session:
        session.query(MergeJob).filter_by(status=MergeJobStatus.RUNNING).update(
            {"status": MergeJobStatus.FAILED, "error_message": INTERRUPTED_MESSAGE, "ended_at": _now()},
            synchronize_session=False,
        )
        session.commit()


def _claim_next(session) -> MergeJob | None:
    job = session.query(MergeJob).filter_by(status=MergeJobStatus.QUEUED).order_by(MergeJob.id).first()
    if job is None:
        return None
    job.status = MergeJobStatus.RUNNING
    job.started_at = _now()
    session.commit()
    return job


def _pr_refs(subtask: Subtask, project: Project) -> dict:
    return {
        "number": subtask.github_pr_number,
        "headRefName": subtask.branch_name,
        "baseRefName": project.default_branch,
    }


def _merge(session, job: MergeJob, merge_fn) -> None:
    subtask = session.get(Subtask, job.subtask_id)
    project = session.get(Project, subtask.project_id)
    merge_fn(project.github_repo, project.repo_path, settings.worktree_base_dir, _pr_refs(subtask, project))
    subtask.lifecycle_state = LifecycleState.MERGED


def _finish(session, job: MergeJob, error: Exception | None) -> None:
    job.status = MergeJobStatus.FAILED if error else MergeJobStatus.SUCCEEDED
    job.error_message = str(error) if error else None
    job.ended_at = _now()
    session.commit()


def process_next_merge(session_factory=None, merge_fn=None) -> bool:
    """待ち行列の先頭のマージを1件処理する

    処理した場合はTrue、待ち行列が空の場合はFalseを返す。
    マージの失敗はジョブに記録し、次のジョブの処理を妨げない。
    """
    factory = session_factory or SessionLocal
    with factory() as session:
        job = _claim_next(session)
        if job is None:
            return False
        try:
            _merge(session, job, merge_fn or merge_pr_with_update)
            error = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("マージジョブ #%s が失敗しました: %s", job.id, exc)
            session.rollback()
            error = exc
        _finish(session, job, error)
        return True


def _merge_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            if process_next_merge():
                continue
        except Exception as exc:  # noqa: BLE001
            # DBの一時的な失敗で処理スレッドを止めない
            logger.warning("マージ待ち行列の処理に失敗しました: %s", exc)
        _wake_event.wait(MERGE_POLL_INTERVAL_SECONDS)
        _wake_event.clear()


def start_merge_loop() -> threading.Event:
    """マージ待ち行列の処理をバックグラウンドで開始する

    処理スレッドは1本のみとし、マージを1件ずつ行う。
    返したEventをsetすると停止する。
    """
    recover_interrupted_merges()
    stop_event = threading.Event()
    threading.Thread(target=_merge_loop, args=(stop_event,), daemon=True).start()
    return stop_event
