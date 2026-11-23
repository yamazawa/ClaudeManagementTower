from pathlib import Path

import pytest

from core import cli_attachments
from core.attachments import AttachmentError
from core.claude_access_rules import default_access_rules
from core.claude_client import _worktree_check


@pytest.fixture(autouse=True)
def worktree_base(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_attachments.settings, "worktree_base_dir", str(tmp_path))
    return tmp_path


def test_save_cli_attachment_stores_outside_repo_per_session(worktree_base):
    entry = cli_attachments.save_cli_attachment(7, "画面.png", b"1")

    assert entry["id"] == "S1"
    assert (worktree_base / "cli-attachments/7/S1/画面.png").read_bytes() == b"1"
    assert cli_attachments.save_cli_attachment(8, "b.txt", b"2")["id"] == "S1"


def test_resolve_cli_attachments_returns_absolute_paths_in_given_order(worktree_base):
    cli_attachments.save_cli_attachment(7, "a.png", b"1")
    cli_attachments.save_cli_attachment(7, "b.txt", b"2")

    resolved = cli_attachments.resolve_cli_attachments(7, ["S2", "S1", "S2"])

    assert [a["id"] for a in resolved] == ["S2", "S1"]
    assert Path(resolved[1]["path"]) == worktree_base / "cli-attachments/7/S1/a.png"
    assert Path(resolved[1]["path"]).is_absolute()


def test_resolve_cli_attachments_rejects_unknown_id():
    cli_attachments.save_cli_attachment(7, "a.png", b"1")

    with pytest.raises(AttachmentError):
        cli_attachments.resolve_cli_attachments(7, ["S1", "S9"])


def test_build_cli_prompt_lists_absolute_paths(worktree_base):
    cli_attachments.save_cli_attachment(7, "a.png", b"1")
    attachments = cli_attachments.resolve_cli_attachments(7, ["S1"])

    prompt = cli_attachments.build_cli_prompt("S1を見て", attachments)

    assert prompt.startswith("S1を見て\n")
    assert f"| S1 | a.png | {attachments[0]['path']} |" in prompt
    assert cli_attachments.ABSOLUTE_PATH_NOTE in prompt


def test_build_cli_prompt_without_attachments_is_unchanged():
    assert cli_attachments.build_cli_prompt("質問", []) == "質問"


def test_cli_attachments_are_readable_but_not_writable_by_claude(worktree_base, monkeypatch):
    monkeypatch.setattr(cli_attachments.settings, "claude_shared_root", str(worktree_base))
    check = _worktree_check(default_access_rules(str(worktree_base / "repo")))
    path = str(Path(cli_attachments.cli_attachments_dir(7)) / "S1" / "a.png")

    assert check("Read", {"file_path": path}) is None
    assert check("Write", {"file_path": path, "content": "x"}) is not None


def test_find_and_delete_cli_attachment():
    cli_attachments.save_cli_attachment(7, "a.png", b"1")

    assert cli_attachments.find_cli_attachment_file(7, "S1").read_bytes() == b"1"
    assert cli_attachments.delete_cli_attachment(7, "S1") is True
    assert cli_attachments.find_cli_attachment_file(7, "S1") is None
