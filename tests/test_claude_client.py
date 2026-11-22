import asyncio

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from core import claude_client
from core.attachments import MAX_ATTACHMENT_BYTES
from core.claude_client import MAX_BUFFER_SIZE, restrict_to_worktree


def _check(worktree, tool_name, tool_input):
    can_use_tool = restrict_to_worktree(worktree)
    return asyncio.run(can_use_tool(tool_name, tool_input, {}))


def test_allows_normal_git_commit_and_push(tmp_path):
    result = _check(str(tmp_path), "Bash", {"command": "git add . && git commit -m test && git push"})
    assert isinstance(result, PermissionResultAllow)


def test_allows_gh_issue_and_pr_commands(tmp_path):
    result = _check(str(tmp_path), "PowerShell", {"command": 'gh issue create --title "x" --body "y"'})
    assert isinstance(result, PermissionResultAllow)


def test_allows_pytest(tmp_path):
    result = _check(str(tmp_path), "Bash", {"command": ".venv/Scripts/python.exe -m pytest -q"})
    assert isinstance(result, PermissionResultAllow)


def test_denies_force_push(tmp_path):
    result = _check(str(tmp_path), "Bash", {"command": "git push --force origin main"})
    assert isinstance(result, PermissionResultDeny)


def test_denies_hard_reset(tmp_path):
    result = _check(str(tmp_path), "Bash", {"command": "git reset --hard HEAD~1"})
    assert isinstance(result, PermissionResultDeny)


def test_denies_worktree_remove(tmp_path):
    result = _check(str(tmp_path), "Bash", {"command": "git worktree remove ../other"})
    assert isinstance(result, PermissionResultDeny)


def test_denies_directory_traversal(tmp_path):
    result = _check(str(tmp_path), "Bash", {"command": "cd .. && rm -rf other-worktree"})
    assert isinstance(result, PermissionResultDeny)


def test_denies_absolute_path_outside_worktree(tmp_path):
    result = _check(str(tmp_path), "PowerShell", {"command": "Remove-Item -Recurse -Force C:/git/ClaudeManagementTower"})
    assert isinstance(result, PermissionResultDeny)


def test_allows_absolute_path_inside_worktree(tmp_path):
    inner = tmp_path / "report.html"
    result = _check(str(tmp_path), "Bash", {"command": f"cat {inner}"})
    assert isinstance(result, PermissionResultAllow)


def test_denies_edit_outside_worktree(tmp_path):
    result = _check(str(tmp_path), "Write", {"file_path": "C:/git/ClaudeManagementTower/core/config.py"})
    assert isinstance(result, PermissionResultDeny)


def test_allows_read_outside_worktree(tmp_path):
    result = _check(str(tmp_path), "Read", {"file_path": "C:/git/DevGuidelines/CommonGuideLine.md"})
    assert isinstance(result, PermissionResultAllow)


def test_allows_glob_and_grep_outside_worktree(tmp_path):
    glob_result = _check(str(tmp_path), "Glob", {"pattern": "*.md", "path": "C:/git/DevGuidelines"})
    grep_result = _check(str(tmp_path), "Grep", {"pattern": "x", "path": "C:/git/DevGuidelines"})
    assert isinstance(glob_result, PermissionResultAllow)
    assert isinstance(grep_result, PermissionResultAllow)


def test_denies_edit_tool_outside_worktree(tmp_path):
    result = _check(str(tmp_path), "Edit", {"file_path": "C:/git/ClaudeManagementTower/core/config.py"})
    assert isinstance(result, PermissionResultDeny)


def test_max_buffer_size_covers_multiple_attachments():
    assert MAX_BUFFER_SIZE >= MAX_ATTACHMENT_BYTES * 10 * 4 // 3


def test_run_claude_passes_max_buffer_size(monkeypatch, tmp_path):
    captured = {}

    async def fake_query(prompt, options):
        captured["options"] = options
        return
        yield

    monkeypatch.setattr(claude_client, "query", fake_query)
    asyncio.run(claude_client.run_claude("prompt", str(tmp_path)))
    assert captured["options"].max_buffer_size == MAX_BUFFER_SIZE


def _check_read_only(root, tool_name, tool_input):
    can_use_tool = claude_client.restrict_to_read_only(root)
    return asyncio.run(can_use_tool(tool_name, tool_input, {}))


def test_read_only_allows_read_inside_root(tmp_path):
    result = _check_read_only(str(tmp_path), "Read", {"file_path": str(tmp_path / "a.py")})
    assert isinstance(result, PermissionResultAllow)


def test_read_only_allows_grep_without_path(tmp_path):
    assert isinstance(_check_read_only(str(tmp_path), "Grep", {"pattern": "x"}), PermissionResultAllow)


def test_read_only_denies_read_outside_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    result = _check_read_only(str(root), "Read", {"file_path": str(tmp_path / "secret.txt")})
    assert isinstance(result, PermissionResultDeny)


def test_read_only_denies_write_and_shell_tools(tmp_path):
    denied_tools = [
        ("Write", {"file_path": str(tmp_path / "a.py"), "content": "x"}),
        ("Edit", {"file_path": str(tmp_path / "a.py")}),
        ("Bash", {"command": "git status"}),
        ("PowerShell", {"command": "Get-ChildItem"}),
        ("WebFetch", {"url": "https://example.com"}),
    ]
    for tool_name, tool_input in denied_tools:
        result = _check_read_only(str(tmp_path), tool_name, tool_input)
        assert isinstance(result, PermissionResultDeny), tool_name


def test_run_read_only_claude_limits_tools(monkeypatch, tmp_path):
    captured = {}

    async def fake_query(prompt, options):
        captured["options"] = options
        return
        yield

    monkeypatch.setattr(claude_client, "query", fake_query)
    asyncio.run(claude_client.run_read_only_claude("prompt", str(tmp_path), "policy"))

    options = captured["options"]
    assert options.tools == claude_client.READ_ONLY_TOOL_NAMES
    assert options.permission_mode == "default"
    assert options.system_prompt["append"] == "policy"
