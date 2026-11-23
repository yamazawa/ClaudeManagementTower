import os
import re
from collections.abc import Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    query,
)

from core.attachments import MAX_ATTACHMENT_BYTES
from core.claude_access_rules import (
    AccessRules,
    command_touches_blocked,
    default_access_rules,
    is_blocked_path,
    is_inside,
)

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

# パスを受け取るツール入力のキー
PATH_INPUT_KEYS = ["file_path", "path", "notebook_path"]

# パスの絞り込みパターンを受け取るツール入力のキー（Globのpatternは別途追加する）
PATTERN_INPUT_KEYS = ["glob"]

GLOB_WILDCARD_PATTERN = re.compile(r"[*?\[{]")
PATH_SEPARATOR_PATTERN = re.compile(r"[\\/]")

DenialCheck = Callable[[str, dict], str | None]


def _command_escapes_writable(command: str, rules: AccessRules) -> bool:
    if DIRECTORY_TRAVERSAL_PATTERN.search(command):
        return True
    tokens = [
        re.split(r'[\s"\'|]', command[match.start():], maxsplit=1)[0]
        for match in WINDOWS_ABS_PATH_PATTERN.finditer(command)
    ]
    return any(not rules.is_writable(token.rstrip("\\/")) for token in tokens)


def _shell_denial(command: str, rules: AccessRules) -> str | None:
    if any(pattern.search(command) for pattern in DANGEROUS_COMMAND_PATTERNS):
        return f"危険な操作のため拒否: {command}"
    if command_touches_blocked(command):
        return f"参照禁止のファイルを含むため拒否: {command}"
    if _command_escapes_writable(command, rules):
        return f"書き込み許可範囲外を操作する可能性があるため拒否: {command}"
    return None


def _input_values(tool_input: dict, keys: list[str]) -> list[str]:
    return [tool_input[key] for key in keys if isinstance(tool_input.get(key), str) and tool_input[key]]


def _input_patterns(tool_name: str, tool_input: dict) -> list[str]:
    keys = PATTERN_INPUT_KEYS + (["pattern"] if tool_name == "Glob" else [])
    return _input_values(tool_input, keys)


def _input_paths(tool_name: str, tool_input: dict) -> list[str]:
    return _input_values(tool_input, PATH_INPUT_KEYS) + _input_patterns(tool_name, tool_input)


def _pattern_target(pattern: str, base: str) -> str | None:
    """パターンが参照し得るフォルダを返す

    最初のワイルドカードを含む要素より前を、固定のフォルダとみなす。
    ワイルドカード以降に親フォルダ指定(..)があり、範囲を特定できない場合はNoneを返す。
    """
    match = GLOB_WILDCARD_PATTERN.search(pattern)
    head = pattern if match is None else pattern[:match.start()]
    prefix = head if match is None else head[:max(head.rfind("/"), head.rfind("\\")) + 1]
    if ".." in PATH_SEPARATOR_PATTERN.split(pattern[len(prefix):]):
        return None
    return os.path.join(base, prefix)


def _read_only_escape(root: str, tool_name: str, tool_input: dict) -> str | None:
    """対象フォルダ外を参照し得る入力値を返す（無ければNone）"""
    base = os.path.join(root, tool_input.get("path") or "")
    paths = _input_values(tool_input, PATH_INPUT_KEYS)
    outside = [path for path in paths if not is_inside(os.path.join(root, path), root)]
    for pattern in _input_patterns(tool_name, tool_input):
        target = _pattern_target(pattern, base)
        if target is None or not is_inside(target, root):
            outside.append(pattern)
    return outside[0] if outside else None


def _blocked_input_denial(tool_name: str, tool_input: dict) -> str | None:
    blocked = [path for path in _input_paths(tool_name, tool_input) if is_blocked_path(path)]
    return f"参照禁止のファイルのため拒否: {blocked[0]}" if blocked else None

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
あなたはClaude管理塔の画面（リポジトリ表示のCLIタブ）から、利用者と対話しています。
開発PCで対話式に実行している時と同様に、利用者の発言に応答する。
1. 作業は対象リポジトリのフォルダ内で行う。
2. 不明点や判断に迷う点は、作業を進めずに利用者へ質問してよい。
   質問は選択肢付きの質問ツールを使わず応答文で行い、利用者の次の発言を待つ。
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
IDEA_MAN_TOOL_NAMES = ["Read", "Glob", "Grep"]


def _to_can_use_tool(check: DenialCheck) -> Callable:
    async def can_use_tool(tool_name, tool_input, context):
        reason = check(tool_name, tool_input)
        if reason is not None:
            return PermissionResultDeny(message=reason)
        return PermissionResultAllow(updated_input=tool_input)

    return can_use_tool


def _to_pre_tool_use_hooks(check: DenialCheck) -> dict:
    """許可確認を経ずに実行されるツールにも、同じ拒否判定を適用するフック

    acceptEdits等では作業フォルダ内の操作がcan_use_toolを経ずに許可されるため。
    """

    async def hook(input_data, tool_use_id, context):
        reason = check(input_data.get("tool_name", ""), input_data.get("tool_input") or {})
        if reason is None:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    return {"PreToolUse": [HookMatcher(matcher=None, hooks=[hook])]}


def _read_only_check(root: str) -> DenialCheck:
    def check(tool_name: str, tool_input: dict) -> str | None:
        if tool_name not in IDEA_MAN_TOOL_NAMES:
            return f"読み取り専用のため拒否: {tool_name}"
        blocked = _blocked_input_denial(tool_name, tool_input)
        if blocked is not None:
            return blocked
        outside = _read_only_escape(root, tool_name, tool_input)
        if outside is not None:
            return f"対象フォルダ外の参照を拒否: {outside}"
        return None

    return check


def restrict_to_read_only(root: str) -> Callable:
    """読み取り専用ツールを、対象フォルダ内に限って許可する

    シェル・ファイル変更・Web取得などは全て拒否する。
    参照禁止のファイルは対象フォルダ内でも拒否する。
    """
    return _to_can_use_tool(_read_only_check(root))


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
        tools=IDEA_MAN_TOOL_NAMES,
        can_use_tool=restrict_to_read_only(root),
        hooks=_to_pre_tool_use_hooks(_read_only_check(root)),
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


def _worktree_check(rules: AccessRules) -> DenialCheck:
    def check(tool_name: str, tool_input: dict) -> str | None:
        if tool_name in SHELL_TOOL_NAMES:
            return _shell_denial(tool_input.get("command", ""), rules)
        blocked = _blocked_input_denial(tool_name, tool_input)
        if blocked is not None or tool_name in READ_ONLY_TOOL_NAMES:
            return blocked
        path = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("notebook_path")
        if path and not rules.is_writable(path):
            return f"書き込み許可範囲外への操作を拒否: {path}"
        return None

    return check


def restrict_to_worktree(worktree: str, rules: AccessRules | None = None) -> Callable:
    """Claude参照ルールに沿って、ツールの使用可否を判定する

    書き込みは対象worktreeと共有ルート配下（他worktree・管理塔自身を除く）に限る。
    読み取り系ツールは場所を問わず許可する。
    参照禁止のファイルは、読み取り・書き込み・シェルのいずれも拒否する。
    """
    return _to_can_use_tool(_worktree_check(rules or default_access_rules(worktree)))


async def run_claude(
    prompt: str,
    worktree: str,
    resume: str | None = None,
    on_message: Callable[[object], None] | None = None,
    policy_prompt: str = AGENT_POLICY_PROMPT,
) -> tuple[str | None, str | None]:
    rules = default_access_rules(worktree)
    options = ClaudeAgentOptions(
        cwd=worktree,
        can_use_tool=restrict_to_worktree(worktree, rules),
        hooks=_to_pre_tool_use_hooks(_worktree_check(rules)),
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
