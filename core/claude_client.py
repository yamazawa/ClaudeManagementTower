import os
from collections.abc import Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    query,
)


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
