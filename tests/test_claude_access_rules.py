from core.claude_access_rules import (
    APP_ROOT,
    AccessRules,
    command_touches_blocked,
    default_access_rules,
    is_blocked_path,
    is_inside,
)
from core.config import settings


def test_is_inside_requires_path_boundary(tmp_path):
    assert is_inside(str(tmp_path / "repo" / "a.py"), str(tmp_path / "repo"))
    assert is_inside(str(tmp_path / "repo"), str(tmp_path / "repo"))
    assert not is_inside(str(tmp_path / "repo-other" / "a.py"), str(tmp_path / "repo"))


def test_is_inside_is_case_insensitive_on_windows(tmp_path):
    assert is_inside(str(tmp_path / "Repo" / "A.py").upper(), str(tmp_path / "repo"))


def test_is_inside_handles_root_with_trailing_separator(tmp_path):
    assert is_inside(str(tmp_path / "repo" / "a.py"), str(tmp_path / "repo") + "\\")
    assert not is_inside(str(tmp_path / "repo-other"), str(tmp_path / "repo") + "\\")


def test_is_inside_resolves_parent_reference(tmp_path):
    assert not is_inside(str(tmp_path / "repo" / ".." / "secret.txt"), str(tmp_path / "repo"))


def test_is_inside_returns_false_for_other_drive(tmp_path):
    other_drive = "Z:\\" if not str(tmp_path).upper().startswith("Z:") else "Y:\\"
    assert not is_inside(other_drive + "a.py", str(tmp_path))


def test_is_blocked_path_matches_any_component():
    assert is_blocked_path("C:/git/repo/.ssh/known_hosts")
    assert is_blocked_path("C:\\git\\repo\\certs\\SERVER.PEM")
    assert not is_blocked_path("C:/git/repo/.env.example")
    assert not is_blocked_path("C:/git/repo/core/config.py")


def test_command_touches_blocked():
    assert command_touches_blocked('Get-Content ".env"')
    assert not command_touches_blocked("$env:PYTHONIOENCODING='utf-8'; ./.venv/Scripts/python.exe -m pytest -q")


def test_worktree_is_writable_even_inside_protected_dir(tmp_path):
    worktree = tmp_path / "worktrees" / "wt"
    rules = AccessRules(str(worktree), str(tmp_path), [str(tmp_path / "worktrees")])
    assert rules.is_writable(str(worktree / "a.py"))
    assert not rules.is_writable(str(tmp_path / "worktrees" / "other" / "a.py"))
    assert rules.is_writable(str(tmp_path / "DevGuidelines" / "a.md"))


def test_default_access_rules_protects_worktrees_and_app_root(tmp_path):
    rules = default_access_rules(str(tmp_path))
    assert rules.shared_root == settings.claude_shared_root
    assert rules.protected_dirs == [settings.worktree_base_dir, APP_ROOT]
