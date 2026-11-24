from collections.abc import Callable

from claude_agent_sdk import ClaudeAgentOptions, query

from core.attachments import MAX_ATTACHMENT_BYTES
from core.claude_access_rules import default_access_rules
from core.claude_permissions import (
    IDEA_MAN_TOOL_NAMES,
    _read_only_check,
    _to_pre_tool_use_hooks,
    _with_denied_tools,
    _worktree_check,
    restrict_to_read_only,
    restrict_to_worktree,
)
from core.claude_prompts import AGENT_POLICY_PROMPT

# SDKとCLIプロセス間のJSONメッセージバッファ上限（SDK既定は1MB）
# 添付画像をReadするとBase64化された内容が1メッセージで返るため既定値では溢れる。
# 添付10件分を想定し、Base64化(約4/3倍)とJSONのオーバーヘッドを1.5倍で見込む。
MAX_BUFFER_ATTACHMENT_COUNT = 10
MAX_BUFFER_OVERHEAD_RATIO = 1.5
MAX_BUFFER_SIZE = int(MAX_ATTACHMENT_BYTES * MAX_BUFFER_ATTACHMENT_COUNT * MAX_BUFFER_OVERHEAD_RATIO)


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


async def run_claude(
    prompt: str,
    worktree: str,
    resume: str | None = None,
    on_message: Callable[[object], None] | None = None,
    policy_prompt: str = AGENT_POLICY_PROMPT,
    denied_tools: dict[str, str] | None = None,
) -> tuple[str | None, str | None]:
    rules = default_access_rules(worktree)
    options = ClaudeAgentOptions(
        cwd=worktree,
        can_use_tool=restrict_to_worktree(worktree, rules, denied_tools),
        hooks=_to_pre_tool_use_hooks(_with_denied_tools(_worktree_check(rules), denied_tools)),
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
