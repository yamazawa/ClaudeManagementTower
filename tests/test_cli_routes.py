import pytest
from fastapi import HTTPException

from app.routes import cli
from core.cli_session import CliSessionBusy, CliSessionNotFound


def test_post_message_rejects_empty_text():
    with pytest.raises(HTTPException) as error:
        cli.post_cli_message(1, cli.SendCliMessageRequest(text="  "))
    assert error.value.status_code == 400


def test_post_message_sends_stripped_text(monkeypatch):
    sent = []
    monkeypatch.setattr(cli, "send_message", lambda session_id, text: sent.append((session_id, text)))

    assert cli.post_cli_message(3, cli.SendCliMessageRequest(text=" 質問 ")) == {"accepted": True}
    assert sent == [(3, "質問")]


@pytest.mark.parametrize(("exc", "status"), [(CliSessionNotFound("x"), 404), (CliSessionBusy("x"), 409)])
def test_post_message_maps_errors(monkeypatch, exc, status):
    def fail(session_id, text):
        raise exc

    monkeypatch.setattr(cli, "send_message", fail)

    with pytest.raises(HTTPException) as error:
        cli.post_cli_message(3, cli.SendCliMessageRequest(text="質問"))
    assert error.value.status_code == status


def test_get_session_404_when_missing(monkeypatch):
    def missing(session_id, after_id):
        raise CliSessionNotFound("x")

    monkeypatch.setattr(cli, "get_session", missing)

    with pytest.raises(HTTPException) as error:
        cli.get_cli_session(9)
    assert error.value.status_code == 404
