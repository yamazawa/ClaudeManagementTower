import os
import re
from collections.abc import Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    query,
)

SHELL_TOOL_NAMES = {"Bash", "PowerShell"}

DANGEROUS_COMMAND_PATTERNS = [
    re.compile(r"push[^|&;\n]*(--force\b|-f\b)", re.IGNORECASE),
    re.compile(r"reset\s+--hard", re.IGNORECASE),
    re.compile(r"clean\s+-[a-z]*f", re.IGNORECASE),
    re.compile(r"worktree\s+(remove|prune)", re.IGNORECASE),
    re.compile(r"branch\s+-D\b", re.IGNORECASE),
    re.compile(r"--git-dir\b|--work-tree\b", re.IGNORECASE),
    re.compile(r"git\s+-C\s", re.IGNORECASE),
]

DIRECTORY_TRAVERSAL_PATTERN = re.compile(r"(?:^|[\s\"'])\.\.(?:[\\/]|$|[\s\"'])")
WINDOWS_ABS_PATH_PATTERN = re.compile(r"[A-Za-z]:[\\/]")


def _command_escapes_worktree(command: str, worktree_abs: str) -> bool:
    if DIRECTORY_TRAVERSAL_PATTERN.search(command):
        return True
    for match in WINDOWS_ABS_PATH_PATTERN.finditer(command):
        token = re.split(r'[\s"\'|]', command[match.start():], maxsplit=1)[0]
        token_abs = os.path.abspath(token.rstrip("\\/"))
        if not token_abs.lower().startswith(worktree_abs.lower()):
            return True
    return False

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
        if tool_name in SHELL_TOOL_NAMES:
            command = tool_input.get("command", "")
            if any(pattern.search(command) for pattern in DANGEROUS_COMMAND_PATTERNS):
                return PermissionResultDeny(message=f"危険な操作のため拒否: {command}")
            if _command_escapes_worktree(command, worktree_abs):
                return PermissionResultDeny(message=f"worktree外を操作する可能性があるため拒否: {command}")
            return PermissionResultAllow(updated_input=tool_input)

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
