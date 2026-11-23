"""CLIタブの対話

リポジトリのフォルダでClaudeを実行し、開発PCで対話式に実行している時のように会話する。
対話はリポジトリの項目として、タイトルとOpen・Closeの状態を持つ。
Webサーバーは応答を待たず、発言ごとに別スレッドでClaudeを実行する。
応答中のClaudeは、開発PCのEscキーのように利用者が中断できる。
画面は発言一覧をポーリングして表示する。
"""

import asyncio
import json
import logging
import threading
from collections.abc import Callable

from claude_agent_sdk import (
    AssistantMessage,
    RateLimitEvent,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from sqlalchemy.orm import sessionmaker

from core.claude_client import CLI_DIALOG_DENIED_TOOLS, CLI_DIALOG_POLICY_PROMPT, run_claude
from core.cli_attachments import build_cli_prompt, resolve_cli_attachments
from core.db import SessionLocal
from core.models import CliMessage, CliSession, Project
from core.rate_limits import record_rate_limit
from core.repo_items import (
    ItemState,
    ensure_open,
    ensure_project,
    get_item_or_raise,
    list_items,
    normalize_title,
    update_item,
)

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
    TOOL_RESULT : ツールの実行結果
    TOOL_ERROR : ツールの実行失敗・拒否の結果
    ERROR : 実行の失敗
    """

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    ERROR = "error"


# ツール実行の表示で、入力の要約に使う項目（先に見つかった項目を使う）
TOOL_SUMMARY_KEYS = ("command", "file_path", "path", "pattern", "url", "description")
TOOL_SUMMARY_MAX_LENGTH = 300
# ツールの実行結果の表示で残す行数・文字数（超えた分は省略する）
TOOL_RESULT_MAX_LINES = 20
TOOL_RESULT_MAX_LENGTH = 2000
TOOL_RESULT_OMITTED_MESSAGE = "...（{count}文字省略）"
INTERRUPTED_MESSAGE = "サーバー再起動により応答が中断されました"
INTERRUPTED_BY_USER_MESSAGE = "利用者が中断しました"
RESULT_ERROR_MESSAGE = "Claudeの実行が失敗しました"
TOOL_ERROR_MESSAGE = "ツールの実行が失敗しました"


class CliSessionBusy(Exception):
    pass


class CliSessionNotRunning(Exception):
    pass


class _TurnCanceller:
    """応答中の1回の発言を、別スレッドから中断する目印

    Claude実行のスレッドが、自身のイベントループと実行中のTaskを登録する。
    中断の要求がTaskの登録前に届いた場合は、登録時に中断する。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self.requested = False

    def attach(self, task: asyncio.Task) -> None:
        with self._lock:
            self._loop, self._task = task.get_loop(), task
            if self.requested:
                task.cancel()

    def cancel(self) -> None:
        with self._lock:
            self.requested = True
            if self._task is not None:
                self._loop.call_soon_threadsafe(self._task.cancel)


# 応答中の対話ごとの中断の目印（対話のID → 目印）
_turn_cancellers: dict[int, _TurnCanceller] = {}
_turn_cancellers_lock = threading.Lock()


def _register_canceller(cli_session_id: int) -> _TurnCanceller:
    canceller = _TurnCanceller()
    with _turn_cancellers_lock:
        _turn_cancellers[cli_session_id] = canceller
    return canceller


def _unregister_canceller(cli_session_id: int, canceller: _TurnCanceller) -> None:
    """自身の目印のみ外す（次の発言の目印は残す）"""
    with _turn_cancellers_lock:
        if _turn_cancellers.get(cli_session_id) is canceller:
            del _turn_cancellers[cli_session_id]


def _find_canceller(cli_session_id: int) -> _TurnCanceller | None:
    with _turn_cancellers_lock:
        return _turn_cancellers.get(cli_session_id)


def _summarize_tool_input(tool_input: dict) -> str:
    summary = next((str(tool_input[key]) for key in TOOL_SUMMARY_KEYS if tool_input.get(key)), None)
    if summary is None:
        summary = json.dumps(tool_input, ensure_ascii=False)
    return summary[:TOOL_SUMMARY_MAX_LENGTH]


def _tool_result_text(content: str | list | None) -> str:
    """ツールの実行結果から文字の部分を取り出す（画像などは除く）"""
    if isinstance(content, str):
        return content
    texts = [item.get("text", "") for item in content or [] if isinstance(item, dict) and item.get("type") == "text"]
    return "\n".join(text for text in texts if text)


def truncate_tool_result(text: str) -> str:
    """ツールの実行結果を、先頭の決まった行数・文字数まで残して省略する"""
    kept = "\n".join(text.splitlines()[:TOOL_RESULT_MAX_LINES])[:TOOL_RESULT_MAX_LENGTH]
    omitted = len(text.rstrip()) - len(kept.rstrip())
    if omitted <= 0:
        return kept.rstrip()
    return f"{kept.rstrip()}\n{TOOL_RESULT_OMITTED_MESSAGE.format(count=omitted)}"


def _tool_result_entry(block: ToolResultBlock) -> tuple[str, str] | None:
    text = truncate_tool_result(_tool_result_text(block.content))
    if block.is_error:
        return CliMessageRole.TOOL_ERROR, text or TOOL_ERROR_MESSAGE
    return (CliMessageRole.TOOL_RESULT, text) if text else None


def _block_entry(block: object) -> tuple[str, str] | None:
    if isinstance(block, TextBlock) and block.text.strip():
        return CliMessageRole.ASSISTANT, block.text
    if isinstance(block, ToolUseBlock):
        return CliMessageRole.TOOL, f"{block.name}: {_summarize_tool_input(block.input or {})}"
    if isinstance(block, ToolResultBlock):
        return _tool_result_entry(block)
    return None


def message_entries(message: object) -> list[tuple[str, str]]:
    """SDKのメッセージから、画面に表示する発言を取り出す

    応答文・ツール実行・ツールの実行結果のみを表示する。
    利用者側のメッセージは、ツールの実行結果のみを取り出す。
    最終結果は応答文と同じ内容のため、失敗時のみ表示する。
    """
    if isinstance(message, (AssistantMessage, UserMessage)) and isinstance(message.content, list):
        entries = [_block_entry(block) for block in message.content]
        return [entry for entry in entries if entry is not None]
    if isinstance(message, ResultMessage) and message.is_error:
        return [(CliMessageRole.ERROR, message.result or RESULT_ERROR_MESSAGE)]
    return []


# 発言一覧に記録する添付ファイルの項目（パスは画面に出さない）
MESSAGE_ATTACHMENT_KEYS = ("id", "filename", "is_image")


def _add_message(session, cli_session_id: int, role: str, content: str, attachments: list[dict] = ()) -> None:
    recorded = [{key: a[key] for key in MESSAGE_ATTACHMENT_KEYS} for a in attachments]
    session.add(
        CliMessage(
            cli_session_id=cli_session_id,
            role=role,
            content=content,
            attachments=json.dumps(recorded, ensure_ascii=False),
        )
    )


def _message_to_dict(message: CliMessage) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "attachments": json.loads(message.attachments or "[]"),
    }


def session_to_dict(cli_session: CliSession) -> dict:
    return {
        "id": cli_session.id,
        "project_id": cli_session.project_id,
        "title": cli_session.title,
        "state": cli_session.state,
        "status": cli_session.status,
        "created_at": cli_session.created_at,
        "updated_at": cli_session.updated_at,
    }


def list_sessions(project_id: int, state: str, session_factory: sessionmaker = SessionLocal) -> list[dict]:
    """CLI一覧（新しい順）"""
    with session_factory() as session:
        return [session_to_dict(s) for s in list_items(session, CliSession, project_id, state)]


def create_session(project_id: int, title: str, session_factory: sessionmaker = SessionLocal) -> dict:
    """CLIの項目をOpenで作成する"""
    value = normalize_title(title)
    with session_factory() as session:
        ensure_project(session, project_id)
        cli_session = CliSession(
            project_id=project_id, title=value, state=ItemState.OPEN, status=CliSessionStatus.IDLE
        )
        session.add(cli_session)
        session.commit()
        return session_to_dict(cli_session)


def update_session(
    cli_session_id: int,
    title: str | None = None,
    state: str | None = None,
    session_factory: sessionmaker = SessionLocal,
) -> dict:
    """タイトル・Open・Closeを変更する"""
    update_item(CliSession, cli_session_id, title, state, session_factory)
    with session_factory() as session:
        return session_to_dict(session.get(CliSession, cli_session_id))


def _claim_turn(
    cli_session_id: int, text: str, session_factory: sessionmaker, attachments: list[dict] = ()
) -> dict:
    """発言を記録して応答中にし、Claude実行に必要な値を返す

    応答中・Closeの対話には発言させない。
    添付ファイルは発言と一緒に記録する。
    """
    with session_factory() as session:
        cli_session = get_item_or_raise(session, CliSession, cli_session_id)
        ensure_open(cli_session)
        if cli_session.status == CliSessionStatus.RUNNING:
            raise CliSessionBusy("Claudeの応答中です")
        cli_session.status = CliSessionStatus.RUNNING
        _add_message(session, cli_session_id, CliMessageRole.USER, text, attachments)
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


def _finish_turn(cli_session_id: int, claude_session_id: str | None, notice: str | None, session_factory) -> None:
    """発言待ちに戻し、続きの発言で使う会話のIDを保存する

    失敗・中断の旨は発言一覧に残す。
    """
    with session_factory() as session:
        cli_session = session.get(CliSession, cli_session_id)
        cli_session.status = CliSessionStatus.IDLE
        if claude_session_id:
            cli_session.claude_session_id = claude_session_id
        if notice is not None:
            _add_message(session, cli_session_id, CliMessageRole.ERROR, notice)
        session.commit()


async def _run_claude_for_dialog(text: str, repo_path: str, resume: str | None, on_message) -> str | None:
    session_id, _ = await run_claude(
        text,
        repo_path,
        resume=resume,
        on_message=on_message,
        policy_prompt=CLI_DIALOG_POLICY_PROMPT,
        denied_tools=CLI_DIALOG_DENIED_TOOLS,
    )
    return session_id


async def _run_cancellable(coro, canceller: _TurnCanceller):
    task = asyncio.ensure_future(coro)
    canceller.attach(task)
    return await task


def _init_session_id(message: object) -> str | None:
    if isinstance(message, SystemMessage) and message.subtype == "init":
        return message.data.get("session_id")
    return None


def run_turn(
    cli_session_id: int,
    text: str,
    target: dict,
    session_factory: sessionmaker = SessionLocal,
    claude_runner: Callable = _run_claude_for_dialog,
    canceller: _TurnCanceller | None = None,
) -> None:
    """1回の発言に対するClaudeの応答を実行する

    失敗・中断は発言一覧に残し、次の発言を受け付けられる状態に戻す。
    中断時も、開始時に通知された会話のIDを保存して続きの発言で使えるようにする。
    """
    canceller = canceller or _register_canceller(cli_session_id)
    started = {}

    def on_message(message: object) -> None:
        started["session_id"] = _init_session_id(message) or started.get("session_id")
        _record_entries(cli_session_id, message, session_factory)

    claude_session_id, notice = None, None
    try:
        runner = claude_runner(text, target["repo_path"], target["resume"], on_message)
        claude_session_id = asyncio.run(_run_cancellable(runner, canceller))
    except asyncio.CancelledError:
        notice = INTERRUPTED_BY_USER_MESSAGE
    except Exception as exc:  # noqa: BLE001
        logger.warning("CLIタブの対話 #%s の応答が失敗しました: %s", cli_session_id, exc)
        notice = str(exc) or RESULT_ERROR_MESSAGE
    _finish_turn(cli_session_id, claude_session_id or started.get("session_id"), notice, session_factory)
    _unregister_canceller(cli_session_id, canceller)


def send_message(
    cli_session_id: int,
    text: str,
    attachment_ids: list[str] = (),
    session_factory: sessionmaker = SessionLocal,
    claude_runner: Callable = _run_claude_for_dialog,
) -> threading.Thread:
    """発言を受け付け、Claudeの応答を別スレッドで開始する

    添付ファイルは、MRの実装指示と同じ形で対応表を発言に付け加えてClaudeに渡す。
    存在しない添付のIDはAttachmentErrorとし、発言を記録しない。
    応答の開始前に中断できるよう、中断の目印はスレッドの開始前に登録する。
    """
    attachments = resolve_cli_attachments(cli_session_id, list(attachment_ids))
    target = _claim_turn(cli_session_id, text, session_factory, attachments)
    prompt = build_cli_prompt(text, attachments)
    canceller = _register_canceller(cli_session_id)
    thread = threading.Thread(
        target=run_turn,
        args=(cli_session_id, prompt, target, session_factory, claude_runner, canceller),
        daemon=True,
    )
    thread.start()
    return thread


def interrupt_turn(cli_session_id: int, session_factory: sessionmaker = SessionLocal) -> None:
    """応答中のClaudeの実行を中断する

    中断の完了（発言待ちへの戻し）は、Claude実行のスレッドが行う。
    実行中のスレッドが無い応答中の対話は、その場で発言待ちに戻す。
    """
    with session_factory() as session:
        cli_session = get_item_or_raise(session, CliSession, cli_session_id)
        if cli_session.status != CliSessionStatus.RUNNING:
            raise CliSessionNotRunning("Claudeは応答中ではありません")
    canceller = _find_canceller(cli_session_id)
    if canceller is not None:
        canceller.cancel()
        return
    _finish_turn(cli_session_id, None, INTERRUPTED_BY_USER_MESSAGE, session_factory)


def ensure_session_open(cli_session_id: int, session_factory: sessionmaker = SessionLocal) -> None:
    """添付ファイルを追加できる対話か確認する

    存在しない・Closeの対話はそれぞれの例外とする。
    """
    with session_factory() as session:
        ensure_open(get_item_or_raise(session, CliSession, cli_session_id))


def get_session(cli_session_id: int, after_id: int = 0, session_factory: sessionmaker = SessionLocal) -> dict:
    """対話の項目と、指定IDより後の発言を返す"""
    with session_factory() as session:
        cli_session = get_item_or_raise(session, CliSession, cli_session_id)
        messages = (
            session.query(CliMessage)
            .filter(CliMessage.cli_session_id == cli_session_id, CliMessage.id > after_id)
            .order_by(CliMessage.id)
            .all()
        )
        return {
            **session_to_dict(cli_session),
            "messages": [_message_to_dict(m) for m in messages],
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
