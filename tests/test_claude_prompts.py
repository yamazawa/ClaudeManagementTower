from core.claude_prompts import CLI_DIALOG_POLICY_PROMPT
from core.cli_tower_tools import TOOL_NAME_PREFIX


def test_cli_dialog_prompt_uses_tower_tools():
    for name in ("create_issue_with_mr", "create_issue", "create_mr"):
        assert f"{TOOL_NAME_PREFIX}{name}" in CLI_DIALOG_POLICY_PROMPT
    assert "gh pr create" in CLI_DIALOG_POLICY_PROMPT


def test_cli_dialog_prompt_creates_mr_without_asking_how_to_proceed():
    assert "進め方を確認せず管理塔ツールでIssueとMRを作成" in CLI_DIALOG_POLICY_PROMPT
    assert "実装は管理塔の画面から実行する" in CLI_DIALOG_POLICY_PROMPT
    assert "直接実装・コミットするのは、利用者が明示的に指示した場合のみ" in CLI_DIALOG_POLICY_PROMPT
    assert "作成前に利用者へ進め方を確認する" not in CLI_DIALOG_POLICY_PROMPT
