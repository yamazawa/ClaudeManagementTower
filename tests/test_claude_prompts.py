from core.claude_prompts import CLI_DIALOG_POLICY_PROMPT
from core.mr_naming import MR_NAME_SEPARATOR


def test_cli_dialog_prompt_follows_tower_naming():
    assert f"{{Issue名}}{MR_NAME_SEPARATOR}{{PR固有名}}" in CLI_DIALOG_POLICY_PROMPT
    assert "issue-{Issue番号}-" in CLI_DIALOG_POLICY_PROMPT
    assert "Related to #{Issue番号}" in CLI_DIALOG_POLICY_PROMPT
