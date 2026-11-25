"""CLIタブのClaudeに渡す管理塔ツール

Issue・MRの作成を、管理塔の画面・アイデアマンと共通の作成処理で行うツールを提供する。
ツールはClaude Agent SDKのプロセス内MCPサーバーとして、対話中のリポジトリに紐づけて渡す。
"""

import asyncio
from collections.abc import Callable

from claude_agent_sdk import create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig
from sqlalchemy.orm import sessionmaker

from core.db import SessionLocal
from core.github_client import get_issue
from core.issue_mr_creation import (
    CREATION_ERRORS,
    EmptyTitleError,
    create_issue,
    create_issue_with_mr,
    create_mr,
)
from core.models import Project

TOWER_SERVER_NAME = "tower"
TOWER_SERVER_VERSION = "1.0.0"
TOOL_NAME_PREFIX = f"mcp__{TOWER_SERVER_NAME}__"

ISSUE_OPEN_STATE = "OPEN"

PROJECT_NOT_FOUND_MESSAGE = "対象リポジトリが見つかりません"
ISSUE_CLOSED_MESSAGE = "Issue #{number} はクローズ済みです。新しいIssueを作成してください。"
ISSUE_CREATED_MESSAGE = "Issue #{number} を作成しました: {url}"
MR_CREATED_MESSAGE = "MR（Draft PR #{pr_number}）「{title}」を作成しました: {url}"
MR_FAILED_MESSAGE = "MRの作成に失敗しました: {reason}"

_STRING = {"type": "string"}
_INSTRUCTION = {"type": "string", "description": "MRの実装指示（.claude-tower/subtask.mdに記録される）"}

ISSUE_SCHEMA = {
    "type": "object",
    "properties": {"title": _STRING, "body": {"type": "string", "description": "Issue本文"}},
    "required": ["title"],
}
ISSUE_WITH_MR_SCHEMA = {
    "type": "object",
    "properties": {**ISSUE_SCHEMA["properties"], "instruction": _INSTRUCTION},
    "required": ["title"],
}
MR_SCHEMA = {
    "type": "object",
    "properties": {
        "issue_number": {"type": "integer"},
        "title": {"type": "string", "description": "MR固有名（MR名のIssue名より後ろの部分）。空欄なら丸数字の連番"},
        "instruction": _INSTRUCTION,
    },
    "required": ["issue_number"],
}


class ToolFailure(Exception):
    pass


def _load_project(project_id: int, session_factory: sessionmaker) -> Project:
    with session_factory() as session:
        project = session.get(Project, project_id)
    if project is None:
        raise ToolFailure(PROJECT_NOT_FOUND_MESSAGE)
    return project


def _mr_line(mr: dict) -> str:
    return MR_CREATED_MESSAGE.format(pr_number=mr["github_pr_number"], title=mr["title"], url=mr["pr_url"])


def _issue_line(issue: dict) -> str:
    return ISSUE_CREATED_MESSAGE.format(number=issue["number"], url=issue["url"])


def run_create_issue(project_id: int, args: dict, session_factory: sessionmaker = SessionLocal) -> str:
    project = _load_project(project_id, session_factory)
    return _issue_line(create_issue(project, args["title"], args.get("body", "")))


def run_create_issue_with_mr(project_id: int, args: dict, session_factory: sessionmaker = SessionLocal) -> str:
    """IssueとMRを作成する

    MR作成のみ失敗した場合も、作成したIssueを伝える。
    """
    project = _load_project(project_id, session_factory)
    created = create_issue_with_mr(
        project, args["title"], args.get("body", ""), args.get("instruction", ""), session_factory=session_factory
    )
    mr_line = _mr_line(created["mr"]) if created["mr"] else MR_FAILED_MESSAGE.format(reason=created["mr_error"])
    return f"{_issue_line(created['issue'])}\n{mr_line}"


def run_create_mr(project_id: int, args: dict, session_factory: sessionmaker = SessionLocal) -> str:
    """オープンなIssueにMRを作成する

    クローズ済みのIssueにはMRを紐づけない。
    """
    project = _load_project(project_id, session_factory)
    issue = get_issue(project.github_repo, args["issue_number"])
    if issue["state"] != ISSUE_OPEN_STATE:
        raise ToolFailure(ISSUE_CLOSED_MESSAGE.format(number=args["issue_number"]))
    mr = create_mr(
        project,
        args["issue_number"],
        suffix=args.get("title", ""),
        instruction=args.get("instruction", ""),
        issue_title=issue["title"],
        session_factory=session_factory,
    )
    return _mr_line(mr)


async def _call(runner: Callable[[int, dict], str], project_id: int, args: dict) -> dict:
    """作成処理を別スレッドで実行し、結果をツールの応答にする

    想定内の失敗は、Claudeが利用者に伝えられるようエラーの応答にする。
    """
    try:
        text = await asyncio.to_thread(runner, project_id, args)
    except (ToolFailure, EmptyTitleError, *CREATION_ERRORS) as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "is_error": True}
    return {"content": [{"type": "text", "text": text}]}


def build_tower_server(project_id: int) -> McpSdkServerConfig:
    """対話中のリポジトリに紐づけた管理塔ツールのMCPサーバー"""

    @tool("create_issue", "管理塔の作成処理でIssueのみを作成する。", ISSUE_SCHEMA)
    async def create_issue_tool(args: dict) -> dict:
        return await _call(run_create_issue, project_id, args)

    @tool(
        "create_issue_with_mr",
        "管理塔の作成処理でIssueとMR（worktree・ブランチ・Draft PR）を作成する。",
        ISSUE_WITH_MR_SCHEMA,
    )
    async def create_issue_with_mr_tool(args: dict) -> dict:
        return await _call(run_create_issue_with_mr, project_id, args)

    @tool(
        "create_mr",
        "管理塔の作成処理で、オープンな既存IssueにMR（worktree・ブランチ・Draft PR）を作成する。",
        MR_SCHEMA,
    )
    async def create_mr_tool(args: dict) -> dict:
        return await _call(run_create_mr, project_id, args)

    return create_sdk_mcp_server(
        name=TOWER_SERVER_NAME,
        version=TOWER_SERVER_VERSION,
        tools=[create_issue_tool, create_issue_with_mr_tool, create_mr_tool],
    )
