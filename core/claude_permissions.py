import os
import re
from collections.abc import Callable

from claude_agent_sdk import HookMatcher, PermissionResultAllow, PermissionResultDeny

from core.claude_access_rules import (
    AccessRules,
    command_touches_blocked,
    default_access_rules,
    is_blocked_path,
    is_inside,
)

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
# 英数字に続く場合（URLのスキーム等）はドライブ指定とみなさない
WINDOWS_ABS_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")

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


# CLIタブの対話で拒否するツールと拒否理由（画面に回答の経路が無いため）
CLI_DIALOG_DENIED_TOOLS = {
    "AskUserQuestion": "CLIタブでは選択肢付きの質問に回答できません。質問は応答文で行い、利用者の次の発言を待ってください。",
}

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


def _with_denied_tools(check: DenialCheck, denied_tools: dict[str, str] | None) -> DenialCheck:
    """指定ツールを理由付きで拒否し、それ以外は元の判定に委ねる"""
    if not denied_tools:
        return check

    def denied_check(tool_name: str, tool_input: dict) -> str | None:
        return denied_tools.get(tool_name) or check(tool_name, tool_input)

    return denied_check


def restrict_to_worktree(
    worktree: str, rules: AccessRules | None = None, denied_tools: dict[str, str] | None = None
) -> Callable:
    """Claude参照ルールに沿って、ツールの使用可否を判定する

    書き込みは対象worktreeと共有ルート配下（他worktree・管理塔自身を除く）に限る。
    読み取り系ツールは場所を問わず許可する。
    参照禁止のファイルは、読み取り・書き込み・シェルのいずれも拒否する。
    denied_toolsに指定したツールは、対応する理由で拒否する。
    """
    check = _worktree_check(rules or default_access_rules(worktree))
    return _to_can_use_tool(_with_denied_tools(check, denied_tools))
