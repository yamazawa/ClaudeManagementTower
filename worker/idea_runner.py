"""アイデア出しジョブの実行

対象リポジトリを読み取り専用で調査させ、提案をideasに保存する。
GitHubへの書き込み・コミット・pushは行わない。
"""

import asyncio
import threading
from collections.abc import Callable

from claude_agent_sdk import RateLimitEvent

from core.claude_client import IDEA_MAN_POLICY_PROMPT, run_read_only_claude
from core.config import settings
from core.db import SessionLocal
from core.idea_context import build_idea_prompt
from core.idea_queue import IdeaJobStatus, finish_idea_job, heartbeat_idea_job
from core.ideas import IdeaParseError, parse_proposals, save_proposals
from core.job_queue import WorkerState, set_worker_state
from core.models import Project
from core.rate_limits import is_rate_limit_error, record_rate_limit

ERROR_EXCERPT_MAX_LENGTH = 2000
RESULT_SUMMARY_FORMAT = "{count}件の提案を保存しました"


def _on_message(message: object) -> None:
    if isinstance(message, RateLimitEvent):
        record_rate_limit(message.rate_limit_info)


async def _run_claude(prompt: str, repo_path: str) -> tuple[str | None, str | None]:
    return await run_read_only_claude(prompt, repo_path, IDEA_MAN_POLICY_PROMPT, on_message=_on_message)


def _repo_path(project_id: int) -> str:
    with SessionLocal() as session:
        return session.get(Project, project_id).repo_path


def _with_heartbeat(idea_job_id: int, worker_id: int, action: Callable[[], None]) -> None:
    stop_event = threading.Event()

    def heartbeat_loop() -> None:
        while not stop_event.wait(settings.job_heartbeat_interval_seconds):
            heartbeat_idea_job(idea_job_id, worker_id)

    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    try:
        action()
    finally:
        stop_event.set()
        thread.join()


def _execute(idea_job_id: int, project_id: int, focus: str, claude_runner: Callable) -> None:
    prompt = build_idea_prompt(project_id, settings.idea_max_proposals, settings.idea_history_limit, focus)
    session_id, result_text = asyncio.run(claude_runner(prompt, _repo_path(project_id)))
    try:
        proposals = parse_proposals(result_text or "", settings.idea_max_proposals)
    except IdeaParseError as exc:
        detail = f"{exc}\n{(result_text or '')[:ERROR_EXCERPT_MAX_LENGTH]}"
        finish_idea_job(idea_job_id, IdeaJobStatus.FAILED, session_id, error_message=detail)
        return
    save_proposals(project_id, idea_job_id, proposals)
    summary = RESULT_SUMMARY_FORMAT.format(count=len(proposals))
    finish_idea_job(idea_job_id, IdeaJobStatus.SUCCEEDED, session_id, result_summary=summary)


def process_idea_job(job: dict, worker_id: int, claude_runner: Callable = _run_claude) -> None:
    """アイデア出しジョブを1件実行する

    実行中はワーカーを占有する。
    失敗はジョブのエラーとして残し、ワーカーは次のジョブに進む。
    """
    idea_job_id = job["idea_job_id"]
    print(f"[worker] idea job {idea_job_id} (project {job['project_id']}) を実行開始")
    set_worker_state(worker_id, state=WorkerState.BUSY, current_job_id=None)
    focus = job.get("focus", "")
    try:
        _with_heartbeat(idea_job_id, worker_id, lambda: _execute(idea_job_id, job["project_id"], focus, claude_runner))
    except Exception as exc:  # noqa: BLE001
        status = IdeaJobStatus.RATE_LIMITED if is_rate_limit_error(str(exc)) else IdeaJobStatus.FAILED
        finish_idea_job(idea_job_id, status, error_message=str(exc))
        print(f"[worker] idea job {idea_job_id} 失敗（{status}）: {exc}")
