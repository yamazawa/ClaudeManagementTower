import os

from fastapi import APIRouter, HTTPException

from app.routes import error_messages as messages
from core.config import settings
from core.job_queue import cleanup_stale_workers, recover_stale_jobs
from core.claude_usage import refresh_usage_if_older
from core.rate_limits import get_rate_limits, latest_event_at
from core.self_sync import SelfSyncAlreadyRunning, read_result, start_self_sync
from core.supervisor_control import (
    COMMAND_RESTART_SERVER,
    COMMAND_START_WORKERS,
    is_supervised,
    request_command,
)

router = APIRouter(prefix="/api/system")


def _request_to_supervisor(command: str) -> dict:
    if not is_supervised():
        raise HTTPException(status_code=409, detail=messages.NOT_SUPERVISED)
    request_command(command)
    return {"accepted": True}


@router.post("/restart-server", status_code=202)
def restart_server() -> dict:
    return _request_to_supervisor(COMMAND_RESTART_SERVER)


@router.post("/start-workers", status_code=202)
def start_workers() -> dict:
    return _request_to_supervisor(COMMAND_START_WORKERS)


@router.post("/sync-self", status_code=202)
def sync_self() -> dict:
    if not is_supervised():
        raise HTTPException(status_code=409, detail=messages.NOT_SUPERVISED)
    try:
        start_self_sync(os.getcwd())
    except SelfSyncAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"accepted": True}


@router.get("/sync-self")
def get_sync_self_result() -> dict:
    result = read_result()
    if result is None:
        raise HTTPException(status_code=404, detail=messages.SELF_SYNC_RESULT_NOT_FOUND)
    return result


@router.post("/cleanup-workers")
def cleanup_workers() -> dict:
    return {
        "removed_worker_ids": cleanup_stale_workers(settings.worker_offline_timeout_seconds),
        "recovered_job_ids": recover_stale_jobs(settings.job_stale_timeout_seconds),
    }


@router.get("/rate-limits")
def rate_limits() -> dict:
    """レート制限の表示内容を返す

    SDK通知の受信後は使用率APIを取得し直し、使用率と状態を揃えてから返す。
    """
    refresh_usage_if_older(latest_event_at())
    return get_rate_limits()
