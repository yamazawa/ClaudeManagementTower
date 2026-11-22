"""アイデアマンの提案（ideas）

提案の保存・一覧・却下を扱う。
GitHubへの書き込み（承認時のIssue・サブタスク作成）はここでは行わない。
"""

import json
import re
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from core.db import SessionLocal
from core.models import Idea


class IdeaStatus:
    """提案の状態

    PROPOSED : 未処理（人間の判断待ち）
    APPROVED_ISSUE_ONLY : Issueのみ作成で承認
    APPROVED_WITH_SUBTASK : Issue＋初回サブタスク作成で承認
    REJECTED : 却下
    ISSUE_CREATED : Issue作成済
    SUBTASK_CREATED : サブタスク作成済
    """

    PROPOSED = "proposed"
    APPROVED_ISSUE_ONLY = "approved_issue_only"
    APPROVED_WITH_SUBTASK = "approved_with_subtask"
    REJECTED = "rejected"
    ISSUE_CREATED = "issue_created"
    SUBTASK_CREATED = "subtask_created"

    # 提案一覧のタブ（未処理／承認済み／却下済み）ごとの状態
    PENDING_STATES = (PROPOSED,)
    APPROVED_STATES = (APPROVED_ISSUE_ONLY, APPROVED_WITH_SUBTASK, ISSUE_CREATED, SUBTASK_CREATED)
    REJECTED_STATES = (REJECTED,)


class IdeaCategory:
    """提案の分類"""

    BUG = "bug"
    FEATURE = "feature"
    REFACTOR = "refactor"
    TECH_DEBT = "tech_debt"
    DOCS = "docs"

    ALL = (BUG, FEATURE, REFACTOR, TECH_DEBT, DOCS)


# 提案一覧のタブ名と、含める状態
IDEA_TABS = {
    "pending": IdeaStatus.PENDING_STATES,
    "approved": IdeaStatus.APPROVED_STATES,
    "rejected": IdeaStatus.REJECTED_STATES,
}

TITLE_MAX_LENGTH = 200
TEXT_MAX_LENGTH = 4000
JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\[.*?\])\s*```", re.DOTALL)


class IdeaNotFound(Exception):
    pass


class IdeaAlreadyDecided(Exception):
    pass


class IdeaParseError(ValueError):
    pass


def _extract_json_array(result_text: str) -> list:
    match = JSON_BLOCK_PATTERN.search(result_text)
    raw = match.group(1) if match else result_text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IdeaParseError(f"提案のJSONを解釈できません: {exc}") from exc
    if not isinstance(data, list):
        raise IdeaParseError("提案のJSONが配列ではありません")
    return data


def _text(item: dict, key: str, max_length: int = TEXT_MAX_LENGTH) -> str:
    return str(item.get(key) or "").strip()[:max_length]


def _related_files(item: dict) -> str:
    files = item.get("related_files") or []
    if isinstance(files, str):
        files = [files]
    return "\n".join(str(f).strip() for f in files if str(f).strip())


def _issue_number(item: dict) -> int | None:
    value = item.get("related_issue_number")
    return value if isinstance(value, int) and value > 0 else None


def _normalize(item: object) -> dict | None:
    """Claudeの提案1件を保存用の値に揃える

    タイトルが無いものは捨てる。
    分類が不明なものはfeatureとして扱う。
    """
    if not isinstance(item, dict) or not _text(item, "title"):
        return None
    category = _text(item, "category")
    return {
        "category": category if category in IdeaCategory.ALL else IdeaCategory.FEATURE,
        "title": _text(item, "title", TITLE_MAX_LENGTH),
        "summary": _text(item, "summary"),
        "detail": _text(item, "detail"),
        "rationale": _text(item, "rationale"),
        "related_files": _related_files(item),
        "related_issue_number": _issue_number(item),
    }


def parse_proposals(result_text: str, max_count: int) -> list[dict]:
    """Claudeの最終応答から提案一覧を取り出す

    応答中のJSON配列（```json ～ ```）を解釈する。
    上限件数を超えた分は捨てる。
    """
    items = [_normalize(item) for item in _extract_json_array(result_text or "")]
    return [item for item in items if item is not None][:max_count]


def save_proposals(
    project_id: int,
    source_job_id: int,
    proposals: list[dict],
    session_factory: sessionmaker = SessionLocal,
) -> list[int]:
    with session_factory() as session:
        ideas = [
            Idea(project_id=project_id, source_job_id=source_job_id, status=IdeaStatus.PROPOSED, **p)
            for p in proposals
        ]
        session.add_all(ideas)
        session.commit()
        return [idea.id for idea in ideas]


def to_dict(idea: Idea) -> dict:
    return {
        "id": idea.id,
        "project_id": idea.project_id,
        "source_job_id": idea.source_job_id,
        "category": idea.category,
        "title": idea.title,
        "summary": idea.summary,
        "detail": idea.detail,
        "rationale": idea.rationale,
        "related_files": [f for f in idea.related_files.split("\n") if f],
        "related_issue_number": idea.related_issue_number,
        "status": idea.status,
        "reject_reason": idea.reject_reason,
        "created_issue_number": idea.created_issue_number,
        "created_subtask_id": idea.created_subtask_id,
        "created_at": idea.created_at,
        "decided_at": idea.decided_at,
    }


def list_ideas(
    project_id: int,
    statuses: tuple[str, ...] | None = None,
    session_factory: sessionmaker = SessionLocal,
) -> list[dict]:
    """提案一覧（新しい順）"""
    with session_factory() as session:
        query = session.query(Idea).filter(Idea.project_id == project_id)
        if statuses is not None:
            query = query.filter(Idea.status.in_(statuses))
        return [to_dict(idea) for idea in query.order_by(Idea.id.desc()).all()]


def reject_idea(idea_id: int, reason: str, session_factory: sessionmaker = SessionLocal) -> dict:
    """提案を却下する

    却下理由は、次回以降のアイデア出しで再提案を抑えるために使う。
    """
    with session_factory() as session:
        idea = session.get(Idea, idea_id)
        if idea is None:
            raise IdeaNotFound("idea not found")
        if idea.status != IdeaStatus.PROPOSED:
            raise IdeaAlreadyDecided("判断済みの提案です")
        idea.status = IdeaStatus.REJECTED
        idea.reject_reason = reason.strip() or None
        idea.decided_at = datetime.now(timezone.utc)
        session.commit()
        return to_dict(idea)
