from collections import Counter, defaultdict

from fastapi import APIRouter
from sqlalchemy import func

from core.db import SessionLocal
from core.deploy import is_deploy_running
from core.lifecycle import LifecycleState
from core.models import ExecutionJob, MergeJob, Subtask
from core.mr_status import MrStatus, derive_mr_status

router = APIRouter(prefix="/api/mr-statuses")


@router.get("")
def get_mr_statuses():
    """全リポジトリのMRの表示ステータス

    ヘッダーのステータスフィルタ用に、ステータスごとのMR数と、
    リポジトリ・Issueごとのステータス別MR数を返す。
    マージされずクローズされたMRは含めない。
    """
    with SessionLocal() as session:
        rows = _subtask_status_rows(session)
    counts = Counter(status for _, _, status in rows)
    issues: dict[int, dict[int, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for project_id, issue_number, status in rows:
        issues[project_id][issue_number][status] += 1
    return {
        "counts": {status: counts.get(status, 0) for status in MrStatus.COUNTED},
        "projects": {
            pid: {number: dict(statuses) for number, statuses in by_issue.items()}
            for pid, by_issue in issues.items()
        },
    }


def _subtask_status_rows(session) -> list[tuple[int, int, str]]:
    """MRごとの（リポジトリID, Issue番号, 表示ステータス）"""
    latest_job = _latest_status_subquery(session, ExecutionJob)
    latest_merge = _latest_status_subquery(session, MergeJob)
    rows = (
        session.query(
            Subtask.project_id,
            Subtask.github_issue_number,
            Subtask.lifecycle_state,
            latest_job.c.status,
            latest_merge.c.status,
        )
        .outerjoin(latest_job, latest_job.c.subtask_id == Subtask.id)
        .outerjoin(latest_merge, latest_merge.c.subtask_id == Subtask.id)
        .filter(Subtask.lifecycle_state != LifecycleState.CANCELED)
        .all()
    )
    deploying = {pid: is_deploy_running(pid) for pid in {r[0] for r in rows}}
    return [
        (pid, number, derive_mr_status(state, job_status, merge_status, deploying[pid]))
        for pid, number, state, job_status, merge_status in rows
    ]


def _latest_status_subquery(session, model):
    """MRごとの最新ジョブの状態（実装ジョブ・マージ待ち行列で共通）"""
    latest_ids = (
        session.query(func.max(model.id).label("id"))
        .group_by(model.subtask_id)
        .subquery()
    )
    return (
        session.query(model.subtask_id, model.status)
        .join(latest_ids, latest_ids.c.id == model.id)
        .subquery()
    )
