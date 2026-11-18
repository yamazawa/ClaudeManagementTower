import os

from fastapi import APIRouter, HTTPException

from core.config import settings
from core.git_client import GitClientError, pull_latest
from core.github_client import GitHubClientError, list_open_pull_requests, merge_pull_request
from core.job_queue import cleanup_stale_workers, recover_stale_jobs
from core.pr_sync import mark_prs_merged
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
        prs = list_open_pull_requests(settings.self_repo)
        merged = []
        for pr in prs:
            if not pr["isDraft"]:
                merge_pull_request(settings.self_repo, pr["number"])
                merged.append(pr["number"])

        mark_prs_merged(settings.self_repo, merged)
        pull_latest(os.getcwd(), "master")
    except (GitHubClientError, GitClientError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    request_command(COMMAND_RESTART_SERVER)
    request_command(COMMAND_RESTART_WORKERS)
    return {"merged_pr_numbers": merged}


@router.post("/cleanup-workers")
def cleanup_workers() -> dict:
    return {
        "removed_worker_ids": cleanup_stale_workers(settings.worker_offline_timeout_seconds),
        "recovered_job_ids": recover_stale_jobs(settings.job_stale_timeout_seconds),
    }
