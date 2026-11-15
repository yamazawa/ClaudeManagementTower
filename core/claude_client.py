import os
from collections.abc import Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    query,
)

AGENT_POLICY_PROMPT = """
あなたはClaude管理塔の自律実装ワーカーです。
対象：GitHub Issueと紐づく1サブタスク（1 PR）。
1. 指示、Issue、既存コード、プロジェクト規約を確認する。
2. 不明点は自ら調査し、合理的な前提を選んで作業を進める。
3. 原則としてユーザーへの問い合わせや応答待ちはしない。
4. 判断した事項と理由、残る不確実性を記録する。
5. 対象worktree・許可範囲で実装、テスト、修正し、変更をコミット・pushする。
6. 変更内容・テスト結果・未解決課題を報告する。
7. 最終的に指定フォーマットのHTMLレポートを.claude-tower/report.htmlに出力する。
8. 機密情報の公開、権限外操作、破壊的操作など安全に
   自律判断できない処理は実行せず、失敗理由を報告する。
9. Issueの自動クローズ、PRの自動マージは行わない。

.claude-tower/report.htmlは以下を含む自己完結したHTMLとする。
1. 対象Issue・サブタスク・ブランチ
2. 実装結果の要約（成功／一部成功／失敗）
3. 実施した変更と主な変更ファイル
4. 自律判断した事項・採用理由・前提
5. 実行したテストと結果（未実施なら理由）
6. 残課題、リスク、レビュー時の確認ポイント

外部スクリプト・外部リソースは読み込まない。
"""


def restrict_to_worktree(worktree: str) -> Callable:
    worktree_abs = os.path.abspath(worktree)

    async def can_use_tool(tool_name, tool_input, context):
        path = tool_input.get("file_path") or tool_input.get("path")
        if path and not os.path.abspath(path).startswith(worktree_abs):
            return PermissionResultDeny(message=f"worktree外への操作を拒否: {path}")
        return PermissionResultAllow(updated_input=tool_input)

    return can_use_tool


async def run_claude(
    prompt: str,
    worktree: str,
    resume: str | None = None,
    on_message: Callable[[object], None] | None = None,
) -> tuple[str | None, str | None]:
    options = ClaudeAgentOptions(
        cwd=worktree,
        can_use_tool=restrict_to_worktree(worktree),
        permission_mode="acceptEdits",
        resume=resume,
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": AGENT_POLICY_PROMPT,
        },
    )
    session_id = None
    result_text = None
    async for message in query(prompt=prompt, options=options):
        if on_message is not None:
            on_message(message)
        cls = type(message).__name__
        if cls == "SystemMessage" and message.subtype == "init":
            session_id = message.data.get("session_id")
        if cls == "ResultMessage":
            result_text = message.result
    return session_id, result_text
