from core.claude_prompts import CLI_DIALOG_POLICY_PROMPT
from core.cli_tower_tools import TOOL_NAME_PREFIX


def test_cli_dialog_prompt_uses_tower_tools():
    for name in ("create_issue_with_mr", "create_issue", "create_mr"):
        assert f"{TOOL_NAME_PREFIX}{name}" in CLI_DIALOG_POLICY_PROMPT
    assert "gh pr create" in CLI_DIALOG_POLICY_PROMPT
