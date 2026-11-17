import os

from fastapi import APIRouter, HTTPException

from core.config import settings
from core.git_client import GitClientError, pull_latest
from core.github_client import GitHubClientError, list_open_pull_requests
from core.job_queue import cleanup_stale_workers, recover_stale_jobs
from core.pr_merger import PrMergeError, merge_pr_with_update
from core.supervisor_control import (
    COMMAND_RESTART_SERVER,
    COMMAND_RESTART_WORKERS,
    COMMAND_START_WORKERS,
    is_supervised,
    request_command,
)

router = APIRouter(prefix="/api/system")

NOT_SUPERVISED_DETAIL = "run_all.py経由で起動していないため実行できません"


def _request_to_supervisor(command: str) -> dict:
    if not is_supervised():
        raise HTTPException(status_code=409, detail=NOT_SUPERVISED_DETAIL)
    request_command(command)
    return {"accepted": True}


@router.post("/restart-server", status_code=202)
def restart_server() -> dict:
    return _request_to_supervisor(COMMAND_RESTART_SERVER)


@router.post("/start-workers", status_code=202)
def start_workers() -> dict:
    return _request_to_supervisor(COMMAND_START_WORKERS)


@router.post("/sync-self")
def sync_self() -> dict:
    if not is_supervised():
        raise HTTPException(status_code=409, detail=NOT_SUPERVISED_DETAIL)

    try:
        prs = [pr for pr in list_open_pull_requests(settings.self_repo) if not pr["isDraft"]]
        results = [_merge_one(pr) for pr in prs]
        pull_latest(os.getcwd(), "master")
    except (GitHubClientError, GitClientError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    request_command(COMMAND_RESTART_SERVER)
    request_command(COMMAND_RESTART_WORKERS)
    return {
        "merged_pr_numbers": [r["number"] for r in results if r["error"] is None],
        "failed_prs": [r for r in results if r["error"] is not None],
    }


def _merge_one(pr: dict) -> dict:
    """1件のPRをマージし、失敗しても他のPRの処理を続けられるよう結果で返す"""
    try:
        merge_pr_with_update(settings.self_repo, os.getcwd(), settings.worktree_base_dir, pr)
    except (GitHubClientError, GitClientError, PrMergeError) as exc:
        return {"number": pr["number"], "error": str(exc)}
    return {"number": pr["number"], "error": None}


@router.post("/cleanup-workers")
def cleanup_workers() -> dict:
    return {
        "removed_worker_ids": cleanup_stale_workers(settings.worker_offline_timeout_seconds),
        "recovered_job_ids": recover_stale_jobs(settings.job_stale_timeout_seconds),
    }
