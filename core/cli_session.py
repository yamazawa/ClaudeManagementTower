"""CLI実行ダイアログの対話

リポジトリのフォルダでClaudeを実行し、開発PCで対話式に実行している時のように会話する。
Webサーバーは応答を待たず、発言ごとに別スレッドでClaudeを実行する。
画面は発言一覧をポーリングして表示する。
"""

import asyncio
import json
import logging
import threading
from collections.abc import Callable

from claude_agent_sdk import AssistantMessage, RateLimitEvent, ResultMessage, TextBlock, ToolUseBlock
from sqlalchemy.orm import sessionmaker

from core.claude_client import CLI_DIALOG_POLICY_PROMPT, run_claude
from core.db import SessionLocal
from core.models import CliMessage, CliSession, Project
from core.rate_limits import record_rate_limit

logger = logging.getLogger(__name__)


class CliSessionStatus:
    """対話の状態

    IDLE : 発言待ち
    RUNNING : Claudeの応答中
    """

    IDLE = "idle"
    RUNNING = "running"


class CliMessageRole:
    """発言の種類（画面の表示と合わせる）

    USER : 利用者の発言
    ASSISTANT : Claudeの応答文
    TOOL : Claudeのツール実行
    ERROR : 実行の失敗
    """

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    ERROR = "error"


# ツール実行の表示で、入力の要約に使う項目（先に見つかった項目を使う）
TOOL_SUMMARY_KEYS = ("command", "file_path", "path", "pattern", "url", "description")
TOOL_SUMMARY_MAX_LENGTH = 300
INTERRUPTED_MESSAGE = "サーバー再起動により応答が中断されました"
RESULT_ERROR_MESSAGE = "Claudeの実行が失敗しました"


class CliSessionNotFound(Exception):
    pass


class CliSessionBusy(Exception):
    pass


def _summarize_tool_input(tool_input: dict) -> str:
    summary = next((str(tool_input[key]) for key in TOOL_SUMMARY_KEYS if tool_input.get(key)), None)
    if summary is None:
        summary = json.dumps(tool_input, ensure_ascii=False)
    return summary[:TOOL_SUMMARY_MAX_LENGTH]


def _block_entry(block: object) -> tuple[str, str] | None:
    if isinstance(block, TextBlock) and block.text.strip():
        return CliMessageRole.ASSISTANT, block.text
    if isinstance(block, ToolUseBlock):
        return CliMessageRole.TOOL, f"{block.name}: {_summarize_tool_input(block.input or {})}"
    return None


def message_entries(message: object) -> list[tuple[str, str]]:
    """SDKのメッセージから、画面に表示する発言を取り出す

    応答文とツール実行のみを表示する。
    最終結果は応答文と同じ内容のため、失敗時のみ表示する。
    """
    if isinstance(message, AssistantMessage):
        entries = [_block_entry(block) for block in message.content]
        return [entry for entry in entries if entry is not None]
    if isinstance(message, ResultMessage) and message.is_error:
        return [(CliMessageRole.ERROR, message.result or RESULT_ERROR_MESSAGE)]
    return []


def _add_message(session, cli_session_id: int, role: str, content: str) -> None:
    session.add(CliMessage(cli_session_id=cli_session_id, role=role, content=content))


def create_session(project_id: int, session_factory: sessionmaker = SessionLocal) -> int:
    with session_factory() as session:
        if session.get(Project, project_id) is None:
            raise CliSessionNotFound("project not found")
        cli_session = CliSession(project_id=project_id, status=CliSessionStatus.IDLE)
        session.add(cli_session)
        session.commit()
        return cli_session.id


def _claim_turn(cli_session_id: int, text: str, session_factory: sessionmaker) -> dict:
    """発言を記録して応答中にし、Claude実行に必要な値を返す

    応答中に重ねて発言させない。
    """
    with session_factory() as session:
        cli_session = session.get(CliSession, cli_session_id)
        if cli_session is None:
            raise CliSessionNotFound("cli session not found")
        if cli_session.status == CliSessionStatus.RUNNING:
            raise CliSessionBusy("Claudeの応答中です")
        cli_session.status = CliSessionStatus.RUNNING
        _add_message(session, cli_session_id, CliMessageRole.USER, text)
        session.commit()
        project = session.get(Project, cli_session.project_id)
        return {"repo_path": project.repo_path, "resume": cli_session.claude_session_id}


def _record_entries(cli_session_id: int, message: object, session_factory: sessionmaker) -> None:
    if isinstance(message, RateLimitEvent):
        record_rate_limit(message.rate_limit_info)
    entries = message_entries(message)
    if not entries:
        return
    with session_factory() as session:
        for role, content in entries:
            _add_message(session, cli_session_id, role, content)
        session.commit()


def _finish_turn(cli_session_id: int, claude_session_id: str | None, error: Exception | None, session_factory) -> None:
    with session_factory() as session:
        cli_session = session.get(CliSession, cli_session_id)
        cli_session.status = CliSessionStatus.IDLE
        if claude_session_id:
            cli_session.claude_session_id = claude_session_id
        if error is not None:
            _add_message(session, cli_session_id, CliMessageRole.ERROR, str(error) or RESULT_ERROR_MESSAGE)
        session.commit()


async def _run_claude_for_dialog(text: str, repo_path: str, resume: str | None, on_message) -> str | None:
    session_id, _ = await run_claude(
        text, repo_path, resume=resume, on_message=on_message, policy_prompt=CLI_DIALOG_POLICY_PROMPT
    )
    return session_id


def run_turn(
    cli_session_id: int,
    text: str,
    target: dict,
    session_factory: sessionmaker = SessionLocal,
    claude_runner: Callable = _run_claude_for_dialog,
) -> None:
    """1回の発言に対するClaudeの応答を実行する

    失敗は発言一覧にエラーとして残し、次の発言を受け付けられる状態に戻す。
    """
    claude_session_id = None
    error = None
    try:
        on_message = lambda message: _record_entries(cli_session_id, message, session_factory)  # noqa: E731
        claude_session_id = asyncio.run(claude_runner(text, target["repo_path"], target["resume"], on_message))
    except Exception as exc:  # noqa: BLE001
        logger.warning("CLI実行ダイアログ #%s の応答が失敗しました: %s", cli_session_id, exc)
        error = exc
    _finish_turn(cli_session_id, claude_session_id, error, session_factory)


def send_message(cli_session_id: int, text: str, session_factory: sessionmaker = SessionLocal) -> None:
    """発言を受け付け、Claudeの応答を別スレッドで開始する"""
    target = _claim_turn(cli_session_id, text, session_factory)
    threading.Thread(
        target=run_turn, args=(cli_session_id, text, target, session_factory), daemon=True
    ).start()


def get_session(cli_session_id: int, after_id: int = 0, session_factory: sessionmaker = SessionLocal) -> dict:
    """対話の状態と、指定IDより後の発言を返す"""
    with session_factory() as session:
        cli_session = session.get(CliSession, cli_session_id)
        if cli_session is None:
            raise CliSessionNotFound("cli session not found")
        messages = (
            session.query(CliMessage)
            .filter(CliMessage.cli_session_id == cli_session_id, CliMessage.id > after_id)
            .order_by(CliMessage.id)
            .all()
        )
        return {
            "id": cli_session.id,
            "status": cli_session.status,
            "messages": [{"id": m.id, "role": m.role, "content": m.content} for m in messages],
        }


def recover_interrupted_sessions(session_factory: sessionmaker = SessionLocal) -> None:
    """起動時に、前回起動中に応答中だった対話を発言待ちに戻す

    中断した応答は再開せず、中断した旨を発言一覧に残す。
    """
    with session_factory() as session:
        running = session.query(CliSession).filter_by(status=CliSessionStatus.RUNNING).all()
        for cli_session in running:
            cli_session.status = CliSessionStatus.IDLE
            _add_message(session, cli_session.id, CliMessageRole.ERROR, INTERRUPTED_MESSAGE)
        session.commit()
