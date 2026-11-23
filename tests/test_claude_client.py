import asyncio
from pathlib import Path

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from core import claude_client
from core.attachments import MAX_ATTACHMENT_BYTES
from core.claude_access_rules import AccessRules
from core.claude_client import MAX_BUFFER_SIZE, restrict_to_worktree


def _rules(worktree):
    """worktreeの2階層上を共有ルート、1階層上をworktree置き場とするルール"""
    worktree_path = Path(worktree)
    shared_root = worktree_path.parent.parent
    return AccessRules(
        worktree=str(worktree_path),
        shared_root=str(shared_root),
        protected_dirs=[str(worktree_path.parent), str(shared_root / "tower")],
    )


def _check(worktree, tool_name, tool_input):
    can_use_tool = restrict_to_worktree(worktree, _rules(worktree))
    return asyncio.run(can_use_tool(tool_name, tool_input, {}))


def _worktree(tmp_path):
    worktree = tmp_path / "git" / "worktrees" / "wt"
    worktree.mkdir(parents=True)
    return worktree


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


def test_allows_write_to_other_repo_in_shared_root(tmp_path):
    worktree = _worktree(tmp_path)
    target = tmp_path / "git" / "DevGuidelines" / "CommonGuideLine.md"
    assert isinstance(_check(str(worktree), "Write", {"file_path": str(target)}), PermissionResultAllow)
    assert isinstance(_check(str(worktree), "Edit", {"file_path": str(target)}), PermissionResultAllow)


def test_allows_shell_on_other_repo_in_shared_root(tmp_path):
    worktree = _worktree(tmp_path)
    target = tmp_path / "git" / "DevGuidelines" / "CommonGuideLine.md"
    result = _check(str(worktree), "PowerShell", {"command": f"Add-Content -Path {target} -Value x"})
    assert isinstance(result, PermissionResultAllow)


def test_denies_write_to_other_worktree(tmp_path):
    worktree = _worktree(tmp_path)
    target = tmp_path / "git" / "worktrees" / "other" / "a.py"
    assert isinstance(_check(str(worktree), "Write", {"file_path": str(target)}), PermissionResultDeny)
    assert isinstance(_check(str(worktree), "Bash", {"command": f"rm {target}"}), PermissionResultDeny)


def test_denies_write_to_tower_app_dir(tmp_path):
    worktree = _worktree(tmp_path)
    target = tmp_path / "git" / "tower" / "core" / "config.py"
    assert isinstance(_check(str(worktree), "Edit", {"file_path": str(target)}), PermissionResultDeny)


def test_denies_write_outside_shared_root(tmp_path):
    worktree = _worktree(tmp_path)
    target = tmp_path / "other" / "a.txt"
    assert isinstance(_check(str(worktree), "Write", {"file_path": str(target)}), PermissionResultDeny)


def test_denies_write_to_sibling_with_same_prefix_as_shared_root(tmp_path):
    worktree = _worktree(tmp_path)
    target = tmp_path / "git-other" / "a.txt"
    assert isinstance(_check(str(worktree), "Write", {"file_path": str(target)}), PermissionResultDeny)
    assert isinstance(_check(str(worktree), "Bash", {"command": f"rm {target}"}), PermissionResultDeny)


def test_allows_write_to_sibling_with_same_prefix_as_protected_dir(tmp_path):
    worktree = _worktree(tmp_path)
    target = tmp_path / "git" / "tower-tools" / "a.py"
    assert isinstance(_check(str(worktree), "Write", {"file_path": str(target)}), PermissionResultAllow)


def test_allows_write_to_worktree_with_different_case(tmp_path):
    worktree = _worktree(tmp_path)
    target = str(worktree / "Core" / "A.py").upper()
    assert isinstance(_check(str(worktree), "Write", {"file_path": target}), PermissionResultAllow)
    assert isinstance(_check(str(worktree), "Bash", {"command": f"cat {target}"}), PermissionResultAllow)


def test_denies_blocked_files_for_read_and_write(tmp_path):
    worktree = _worktree(tmp_path)
    blocked_paths = [
        worktree / ".env",
        worktree / "config" / ".env.local",
        tmp_path / "git" / "DevGuidelines" / "server.pem",
        tmp_path / "home" / ".ssh" / "config",
        tmp_path / "home" / ".claude" / ".credentials.json",
    ]
    for path in blocked_paths:
        for tool_name in ["Read", "Write", "Edit"]:
            result = _check(str(worktree), tool_name, {"file_path": str(path)})
            assert isinstance(result, PermissionResultDeny), f"{tool_name} {path}"


def test_denies_blocked_files_in_glob_and_grep(tmp_path):
    worktree = _worktree(tmp_path)
    assert isinstance(_check(str(worktree), "Glob", {"pattern": "**/.env"}), PermissionResultDeny)
    assert isinstance(_check(str(worktree), "Grep", {"pattern": "x", "glob": "*.key"}), PermissionResultDeny)
    assert isinstance(_check(str(worktree), "Grep", {"pattern": "x", "path": ".ssh"}), PermissionResultDeny)


def test_denies_blocked_files_in_shell(tmp_path):
    worktree = _worktree(tmp_path)
    for command in ["cat .env", "Get-Content 'config/.env.production'", "type id_rsa", "cp a.txt C:/x/.aws/credentials"]:
        assert isinstance(_check(str(worktree), "Bash", {"command": command}), PermissionResultDeny), command


def test_allows_env_example(tmp_path):
    worktree = _worktree(tmp_path)
    assert isinstance(_check(str(worktree), "Read", {"file_path": str(worktree / ".env.example")}), PermissionResultAllow)
    assert isinstance(_check(str(worktree), "Bash", {"command": "cat .env.example"}), PermissionResultAllow)


def test_pre_tool_use_hook_denies_blocked_file(tmp_path):
    worktree = _worktree(tmp_path)
    hooks = claude_client._to_pre_tool_use_hooks(claude_client._worktree_check(_rules(worktree)))
    hook = hooks["PreToolUse"][0].hooks[0]
    denied = asyncio.run(hook({"tool_name": "Read", "tool_input": {"file_path": str(worktree / ".env")}}, None, {}))
    allowed = asyncio.run(hook({"tool_name": "Read", "tool_input": {"file_path": str(worktree / "a.py")}}, None, {}))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert allowed == {}


def test_run_claude_registers_pre_tool_use_hook(monkeypatch, tmp_path):
    captured = {}

    async def fake_query(prompt, options):
        captured["options"] = options
        return
        yield

    monkeypatch.setattr(claude_client, "query", fake_query)
    asyncio.run(claude_client.run_claude("prompt", str(tmp_path)))
    assert "PreToolUse" in captured["options"].hooks


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


def _read_only_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return str(root)


def test_read_only_denies_sibling_with_same_prefix(tmp_path):
    root = _read_only_root(tmp_path)
    result = _check_read_only(root, "Read", {"file_path": str(tmp_path / "repo-other" / "a.py")})
    assert isinstance(result, PermissionResultDeny)


def test_read_only_allows_read_with_different_case(tmp_path):
    root = _read_only_root(tmp_path)
    result = _check_read_only(root, "Read", {"file_path": str(tmp_path / "Repo" / "A.py").upper()})
    assert isinstance(result, PermissionResultAllow)


def test_read_only_resolves_relative_path_from_root(tmp_path):
    root = _read_only_root(tmp_path)
    assert isinstance(_check_read_only(root, "Read", {"file_path": "core/a.py"}), PermissionResultAllow)
    assert isinstance(_check_read_only(root, "Read", {"file_path": "../secret.txt"}), PermissionResultDeny)


def test_read_only_denies_absolute_pattern_outside_root(tmp_path):
    root = _read_only_root(tmp_path)
    outside = str(tmp_path / "other")
    denied_inputs = [
        ("Glob", {"pattern": outside + "/**/*.py"}),
        ("Glob", {"pattern": "../other/*.py"}),
        ("Glob", {"pattern": "**/../../*.py"}),
        ("Grep", {"pattern": "x", "glob": outside + "/*.py"}),
    ]
    for tool_name, tool_input in denied_inputs:
        result = _check_read_only(root, tool_name, tool_input)
        assert isinstance(result, PermissionResultDeny), tool_input


def test_read_only_allows_pattern_inside_root(tmp_path):
    root = _read_only_root(tmp_path)
    allowed_inputs = [
        ("Glob", {"pattern": "**/*.py"}),
        ("Glob", {"pattern": root + "/core/*.py"}),
        ("Glob", {"pattern": "*.py", "path": root + "/core"}),
        ("Grep", {"pattern": "C:/x/../*", "glob": "*.py"}),
    ]
    for tool_name, tool_input in allowed_inputs:
        result = _check_read_only(root, tool_name, tool_input)
        assert isinstance(result, PermissionResultAllow), tool_input


def test_read_only_denies_blocked_file_inside_root(tmp_path):
    result = _check_read_only(str(tmp_path), "Read", {"file_path": str(tmp_path / ".env")})
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
    assert options.tools == claude_client.IDEA_MAN_TOOL_NAMES
    assert "PreToolUse" in options.hooks
    assert options.permission_mode == "default"
    assert options.system_prompt["append"] == "policy"
