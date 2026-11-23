import asyncio

import pytest
from fastapi import HTTPException

from app.routes import cli
from core import cli_attachments
from core.attachments import AttachmentError
from core.cli_session import CliSessionBusy, CliSessionNotRunning
from core.repo_items import RepoItemClosed, RepoItemInvalid, RepoItemNotFound


def test_post_message_rejects_empty_text():
    with pytest.raises(HTTPException) as error:
        cli.post_cli_message(1, cli.SendCliMessageRequest(text="  "))
    assert error.value.status_code == 400


def test_post_message_sends_stripped_text(monkeypatch):
    sent = []
    monkeypatch.setattr(cli, "send_message", lambda session_id, text, ids: sent.append((session_id, text, ids)))

    assert cli.post_cli_message(3, cli.SendCliMessageRequest(text=" 質問 ")) == {"accepted": True}
    assert sent == [(3, "質問", [])]


def test_post_message_passes_attachment_ids(monkeypatch):
    sent = []
    monkeypatch.setattr(cli, "send_message", lambda session_id, text, ids: sent.append(ids))

    cli.post_cli_message(3, cli.SendCliMessageRequest(text="S1を見て", attachment_ids=["S1"]))

    assert sent == [["S1"]]


@pytest.mark.parametrize(
    ("exc", "status"),
    [(RepoItemNotFound("x"), 404), (CliSessionBusy("x"), 409), (RepoItemClosed("x"), 409), (AttachmentError("x"), 400)],
)
def test_post_message_maps_errors(monkeypatch, exc, status):
    def fail(session_id, text, ids):
        raise exc

    monkeypatch.setattr(cli, "send_message", fail)

    with pytest.raises(HTTPException) as error:
        cli.post_cli_message(3, cli.SendCliMessageRequest(text="質問"))
    assert error.value.status_code == status


def test_post_interrupt_requests_interrupt(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "interrupt_turn", calls.append)

    assert cli.post_cli_interrupt(3) == {"accepted": True}
    assert calls == [3]


@pytest.mark.parametrize(("exc", "status"), [(RepoItemNotFound("x"), 404), (CliSessionNotRunning("x"), 409)])
def test_post_interrupt_maps_errors(monkeypatch, exc, status):
    def fail(session_id):
        raise exc

    monkeypatch.setattr(cli, "interrupt_turn", fail)

    with pytest.raises(HTTPException) as error:
        cli.post_cli_interrupt(3)
    assert error.value.status_code == status


def test_get_session_404_when_missing(monkeypatch):
    def missing(session_id, after_id):
        raise RepoItemNotFound("x")

    monkeypatch.setattr(cli, "get_session", missing)

    with pytest.raises(HTTPException) as error:
        cli.get_cli_session(9)
    assert error.value.status_code == 404


@pytest.mark.parametrize(("exc", "status"), [(RepoItemNotFound("x"), 404), (RepoItemInvalid("x"), 400)])
def test_create_session_maps_errors(monkeypatch, exc, status):
    def fail(project_id, title):
        raise exc

    monkeypatch.setattr(cli, "create_session", fail)

    with pytest.raises(HTTPException) as error:
        cli.create_cli_session(cli.CreateCliSessionRequest(project_id=1, title=""))
    assert error.value.status_code == status


def test_patch_session_passes_title_and_state(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "update_session", lambda *args: calls.append(args) or {"id": 2})

    cli.patch_cli_session(2, cli.RepoItemPatch(state="closed"))

    assert calls == [(2, None, "closed")]


def test_patch_request_rejects_unknown_state():
    with pytest.raises(ValueError):
        cli.RepoItemPatch(state="deleted")


class _Upload:
    def __init__(self, filename, data):
        self.filename = filename
        self._data = data

    async def read(self):
        return self._data


@pytest.fixture
def attachment_base(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_attachments.settings, "worktree_base_dir", str(tmp_path))
    monkeypatch.setattr(cli, "ensure_session_open", lambda session_id: None)
    return tmp_path


def test_upload_attachment_saves_and_can_be_fetched_and_removed(attachment_base):
    entry = asyncio.run(cli.upload_cli_attachment(5, _Upload("画面.png", b"1")))

    assert (entry["id"], entry["filename"], entry["is_image"]) == ("S1", "画面.png", True)
    assert cli.get_cli_attachment_file(5, "S1").path.name == "画面.png"
    assert cli.remove_cli_attachment(5, "S1") == {"id": "S1"}
    with pytest.raises(HTTPException) as error:
        cli.get_cli_attachment_file(5, "S1")
    assert error.value.status_code == 404


def test_upload_attachment_rejects_closed_session(attachment_base, monkeypatch):
    def closed(session_id):
        raise RepoItemClosed("x")

    monkeypatch.setattr(cli, "ensure_session_open", closed)

    with pytest.raises(HTTPException) as error:
        asyncio.run(cli.upload_cli_attachment(5, _Upload("a.png", b"1")))
    assert error.value.status_code == 409


def test_upload_attachment_rejects_invalid_filename(attachment_base):
    with pytest.raises(HTTPException) as error:
        asyncio.run(cli.upload_cli_attachment(5, _Upload("..", b"1")))
    assert error.value.status_code == 400


def test_remove_attachment_404_when_missing(attachment_base):
    with pytest.raises(HTTPException) as error:
        cli.remove_cli_attachment(5, "S9")
    assert error.value.status_code == 404
