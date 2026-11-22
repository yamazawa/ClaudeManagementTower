import os
import re
from collections.abc import Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    query,
)

from core.attachments import MAX_ATTACHMENT_BYTES

# SDKとCLIプロセス間のJSONメッセージバッファ上限（SDK既定は1MB）
# 添付画像をReadするとBase64化された内容が1メッセージで返るため既定値では溢れる。
# 添付10件分を想定し、Base64化(約4/3倍)とJSONのオーバーヘッドを1.5倍で見込む。
MAX_BUFFER_ATTACHMENT_COUNT = 10
MAX_BUFFER_OVERHEAD_RATIO = 1.5
MAX_BUFFER_SIZE = int(MAX_ATTACHMENT_BYTES * MAX_BUFFER_ATTACHMENT_COUNT * MAX_BUFFER_OVERHEAD_RATIO)

SHELL_TOOL_NAMES = {"Bash", "PowerShell"}

# worktree外でも参照を許可する読み取り専用ツール
READ_ONLY_TOOL_NAMES = {"Read", "Glob", "Grep", "LS", "NotebookRead"}

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

CONFLICT_RESOLUTION_POLICY_PROMPT = """
あなたはClaude管理塔のマージ競合解決ワーカーです。
対象：ベースブランチを取り込み中で競合しているPRブランチのworktree。
1. 競合ファイルを読み、両側の変更意図を確認する。
2. 両側の変更を活かす形で競合マーカーを解消する。
3. 解消したファイルを git add する。
4. テストがあれば実行し、失敗したら修正して git add する。
5. git commit・git push・git merge --abort は行わない。
6. 判断に迷う箇所と採用理由を最終応答で報告する。
7. 機密情報の公開、権限外操作、破壊的操作は行わない。
"""


CLI_DIALOG_POLICY_PROMPT = """
あなたはClaude管理塔の画面（CLI実行ダイアログ）から、利用者と対話しています。
開発PCで対話式に実行している時と同様に、利用者の発言に応答する。
1. 作業は対象リポジトリのフォルダ内で行う。
2. 不明点や判断に迷う点は、作業を進めずに利用者へ質問してよい。
3. 機密情報の公開、権限外操作、破壊的操作は行わない。
4. Issueのクローズ、PRのマージは利用者が明示的に指示した場合のみ行う。
"""


IDEA_MAN_POLICY_PROMPT = """
あなたはClaude管理塔のアイデアマンです。
対象：指定リポジトリのコード・ドキュメント・過去の実行履歴。
1. コードの変更・コミット・push・GitHubへの書き込み操作は行わない（読み取り専用）。
2. 既存のOpen Issue一覧を確認し、重複する提案は作らない。
3. 1回の実行で提案する件数は指示された上限件数までとする。
4. 各提案には、対象ファイル・行・観測した事象など根拠を明記する。
5. 機密情報・個人情報を提案の本文に記載しない。
6. 提案はあくまで案であり、Issue・PRの作成はこのジョブの中では行わない。
"""

# アイデアマンが使えるツール（読み取り専用）
READ_ONLY_TOOL_NAMES = ["Read", "Glob", "Grep"]


def _is_inside(path: str, root_abs: str) -> bool:
    return os.path.abspath(path).lower().startswith(root_abs.lower())


def restrict_to_read_only(root: str) -> Callable:
    """読み取り専用ツールを、対象フォルダ内に限って許可する

    シェル・ファイル変更・Web取得などは全て拒否する。
    """
    root_abs = os.path.abspath(root)

    async def can_use_tool(tool_name, tool_input, context):
        if tool_name not in READ_ONLY_TOOL_NAMES:
            return PermissionResultDeny(message=f"読み取り専用のため拒否: {tool_name}")
        path = tool_input.get("file_path") or tool_input.get("path")
        if path and not _is_inside(path, root_abs):
            return PermissionResultDeny(message=f"対象フォルダ外の参照を拒否: {path}")
        return PermissionResultAllow(updated_input=tool_input)

    return can_use_tool


async def run_read_only_claude(
    prompt: str,
    root: str,
    policy_prompt: str,
    on_message: Callable[[object], None] | None = None,
) -> tuple[str | None, str | None]:
    """読み取り専用でClaudeを実行する

    使えるツールを読み取り系に絞り、許可確認でも読み取り以外を拒否する。
    """
    options = ClaudeAgentOptions(
        cwd=root,
        tools=READ_ONLY_TOOL_NAMES,
        can_use_tool=restrict_to_read_only(root),
        permission_mode="default",
        max_buffer_size=MAX_BUFFER_SIZE,
        system_prompt={"type": "preset", "preset": "claude_code", "append": policy_prompt},
    )
    return await _collect_result(query(prompt=prompt, options=options), on_message)


async def _collect_result(messages, on_message) -> tuple[str | None, str | None]:
    session_id = None
    result_text = None
    async for message in messages:
        if on_message is not None:
            on_message(message)
        cls = type(message).__name__
        if cls == "SystemMessage" and message.subtype == "init":
            session_id = message.data.get("session_id")
        if cls == "ResultMessage":
            result_text = message.result
    return session_id, result_text


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

        if tool_name in READ_ONLY_TOOL_NAMES:
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
    policy_prompt: str = AGENT_POLICY_PROMPT,
) -> tuple[str | None, str | None]:
    options = ClaudeAgentOptions(
        cwd=worktree,
        can_use_tool=restrict_to_worktree(worktree),
        permission_mode="acceptEdits",
        resume=resume,
        max_buffer_size=MAX_BUFFER_SIZE,
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": policy_prompt,
        },
    )
    return await _collect_result(query(prompt=prompt, options=options), on_message)
