import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from sqlalchemy.orm import sessionmaker

from core import cli_attachments as cli_attachments
from core import cli_session
from core.attachments import AttachmentError
from core.cli_session import CliMessageRole, CliSessionStatus
from core.db import init_db, make_engine
from core.models import CliSession, Project
from core.repo_items import ItemState, RepoItemClosed, RepoItemInvalid, RepoItemNotFound


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Project(id=1, name="p", github_repo="owner/repo", repo_path="C:/repo", default_branch="master"))
        session.commit()
    return factory


def _assistant(*blocks):
    return AssistantMessage(content=list(blocks), model="m")


def _result(is_error, result="r"):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id="s",
        result=result,
    )


def test_message_entries_extracts_text_and_tool_use():
    message = _assistant(
        TextBlock(text="調べます"),
        TextBlock(text="  "),
        ToolUseBlock(id="t", name="Bash", input={"command": "git status"}),
    )

    assert cli_session.message_entries(message) == [
        (CliMessageRole.ASSISTANT, "調べます"),
        (CliMessageRole.TOOL, "Bash: git status"),
    ]


def test_message_entries_shows_result_only_on_error():
    assert cli_session.message_entries(_result(False)) == []
    assert cli_session.message_entries(_result(True, "失敗")) == [(CliMessageRole.ERROR, "失敗")]


def test_create_session_rejects_unknown_project(session_factory):
    with pytest.raises(RepoItemNotFound):
        cli_session.create_session(99, "調査", session_factory=session_factory)


def test_create_session_rejects_empty_title(session_factory):
    with pytest.raises(RepoItemInvalid):
        cli_session.create_session(1, "  ", session_factory=session_factory)


def test_create_session_is_open_with_stripped_title(session_factory):
    created = cli_session.create_session(1, " 調査 ", session_factory=session_factory)

    assert (created["title"], created["state"], created["status"]) == ("調査", ItemState.OPEN, CliSessionStatus.IDLE)


def test_list_sessions_filters_by_state_newest_first(session_factory):
    first = cli_session.create_session(1, "1件目", session_factory=session_factory)["id"]
    second = cli_session.create_session(1, "2件目", session_factory=session_factory)["id"]
    closed = cli_session.create_session(1, "閉じる", session_factory=session_factory)["id"]
    cli_session.update_session(closed, state=ItemState.CLOSED, session_factory=session_factory)

    opened = cli_session.list_sessions(1, ItemState.OPEN, session_factory=session_factory)
    closed_list = cli_session.list_sessions(1, ItemState.CLOSED, session_factory=session_factory)

    assert [s["id"] for s in opened] == [second, first]
    assert [s["id"] for s in closed_list] == [closed]


def test_update_session_changes_only_given_values(session_factory):
    session_id = cli_session.create_session(1, "調査", session_factory=session_factory)["id"]

    renamed = cli_session.update_session(session_id, title="再調査", session_factory=session_factory)

    assert (renamed["title"], renamed["state"]) == ("再調査", ItemState.OPEN)


def test_claim_turn_rejects_closed_session(session_factory):
    session_id = cli_session.create_session(1, "調査", session_factory=session_factory)["id"]
    cli_session.update_session(session_id, state=ItemState.CLOSED, session_factory=session_factory)

    with pytest.raises(RepoItemClosed):
        cli_session._claim_turn(session_id, "質問", session_factory)


def _claim(session_factory, text="こんにちは"):
    session_id = cli_session.create_session(1, "調査", session_factory=session_factory)["id"]
    target = cli_session._claim_turn(session_id, text, session_factory)
    return session_id, target


def test_claim_turn_records_user_message_and_rejects_while_running(session_factory):
    session_id, target = _claim(session_factory)

    assert target == {"repo_path": "C:/repo", "resume": None}
    state = cli_session.get_session(session_id, session_factory=session_factory)
    assert state["status"] == CliSessionStatus.RUNNING
    assert [(m["role"], m["content"]) for m in state["messages"]] == [(CliMessageRole.USER, "こんにちは")]
    with pytest.raises(cli_session.CliSessionBusy):
        cli_session._claim_turn(session_id, "続き", session_factory)


def test_claim_turn_records_attachment_names_without_paths(session_factory):
    session_id = cli_session.create_session(1, "調査", session_factory=session_factory)["id"]
    attachment = {"id": "S1", "filename": "画面.png", "path": "C:/x/S1/画面.png", "is_image": True}

    cli_session._claim_turn(session_id, "S1を見て", session_factory, [attachment])

    state = cli_session.get_session(session_id, session_factory=session_factory)
    assert state["messages"][0]["attachments"] == [{"id": "S1", "filename": "画面.png", "is_image": True}]


def test_send_message_rejects_unknown_attachment_without_recording(session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(cli_attachments.settings, "worktree_base_dir", str(tmp_path))
    session_id = cli_session.create_session(1, "調査", session_factory=session_factory)["id"]

    with pytest.raises(AttachmentError):
        cli_session.send_message(session_id, "S1を見て", ["S1"], session_factory=session_factory)

    state = cli_session.get_session(session_id, session_factory=session_factory)
    assert (state["status"], state["messages"]) == (CliSessionStatus.IDLE, [])


def test_send_message_passes_prompt_with_attachment_table(session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(cli_attachments.settings, "worktree_base_dir", str(tmp_path))
    session_id = cli_session.create_session(1, "調査", session_factory=session_factory)["id"]
    cli_attachments.save_cli_attachment(session_id, "a.png", b"1")
    started = []

    class FakeThread:
        def __init__(self, target, args, daemon):
            started.append(args)

        def start(self):
            pass

    monkeypatch.setattr(cli_session.threading, "Thread", FakeThread)

    cli_session.send_message(session_id, "S1を見て", ["S1"], session_factory=session_factory)

    prompt = started[0][1]
    assert prompt.startswith("S1を見て\n")
    assert str(tmp_path / "cli-attachments" / str(session_id) / "S1" / "a.png") in prompt
    state = cli_session.get_session(session_id, session_factory=session_factory)
    assert state["messages"][0]["content"] == "S1を見て"


def test_run_turn_records_reply_and_keeps_claude_session(session_factory):
    session_id, target = _claim(session_factory)

    async def fake_runner(text, repo_path, resume, on_message):
        on_message(_assistant(TextBlock(text=f"{text}への応答")))
        return "claude-1"

    cli_session.run_turn(session_id, "こんにちは", target, session_factory, fake_runner)

    state = cli_session.get_session(session_id, after_id=1, session_factory=session_factory)
    assert state["status"] == CliSessionStatus.IDLE
    assert [m["content"] for m in state["messages"]] == ["こんにちはへの応答"]
    assert cli_session._claim_turn(session_id, "続き", session_factory)["resume"] == "claude-1"


def test_run_turn_records_error_and_returns_to_idle(session_factory):
    session_id, target = _claim(session_factory)

    async def failing_runner(text, repo_path, resume, on_message):
        raise RuntimeError("CLIが見つからない")

    cli_session.run_turn(session_id, "こんにちは", target, session_factory, failing_runner)

    state = cli_session.get_session(session_id, after_id=1, session_factory=session_factory)
    assert state["status"] == CliSessionStatus.IDLE
    assert [(m["role"], m["content"]) for m in state["messages"]] == [(CliMessageRole.ERROR, "CLIが見つからない")]


def test_recover_interrupted_sessions_returns_running_to_idle(session_factory):
    session_id, _ = _claim(session_factory)

    cli_session.recover_interrupted_sessions(session_factory)

    with session_factory() as session:
        assert session.get(CliSession, session_id).status == CliSessionStatus.IDLE
    state = cli_session.get_session(session_id, after_id=1, session_factory=session_factory)
    assert [m["content"] for m in state["messages"]] == [cli_session.INTERRUPTED_MESSAGE]
