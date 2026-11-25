"""アイデアマンの提案の承認

承認時の状態遷移と、Issue本文・サブタスク指示の組み立てを扱う。
GitHubへの書き込み（Issue・サブタスク作成）は呼び出し側で共通の作成処理を使う。
"""

from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from core.db import SessionLocal
from core.ideas import IdeaAlreadyDecided, IdeaNotFound, IdeaStatus, to_dict
from core.models import Idea


class ApprovalMode:
    """承認の種類

    ISSUE_ONLY : Issueのみ作成
    WITH_SUBTASK : Issue作成＋初回サブタスク（実装着手）も作成
    """

    ISSUE_ONLY = "issue_only"
    WITH_SUBTASK = "with_subtask"


ISSUE_TITLE_PREFIX = "[IdeaMan] "
ISSUE_BODY_FOOTER = "アイデアマンの提案（ID: {idea_id}）から作成"
SUBTASK_INSTRUCTION_HEADER = "アイデアマンの提案を実装する。"


class IdeaApprovalNotAllowed(Exception):
    pass


def _claim_target(idea: Idea, mode: str) -> str:
    """承認操作で遷移する状態

    既存Issue配下の提案は、Issueを新規作成せずサブタスクのみ作成する。
    Issue作成済みの提案は、後からサブタスクも作成できる（作成失敗時の再実行を兼ねる）。
    """
    if mode == ApprovalMode.ISSUE_ONLY and idea.related_issue_number is not None:
        raise IdeaApprovalNotAllowed("既存Issue配下の提案はサブタスク作成のみ承認できます")
    if idea.status == IdeaStatus.PROPOSED:
        return IdeaStatus.APPROVED_ISSUE_ONLY if mode == ApprovalMode.ISSUE_ONLY else IdeaStatus.APPROVED_WITH_SUBTASK
    if idea.status == IdeaStatus.ISSUE_CREATED and mode == ApprovalMode.WITH_SUBTASK:
        return IdeaStatus.APPROVED_WITH_SUBTASK
    raise IdeaAlreadyDecided("判断済みの提案です")


def claim_idea(idea_id: int, mode: str, session_factory: sessionmaker = SessionLocal) -> dict:
    """承認処理中の状態にして、提案の内容を返す

    状態を条件にした更新で、同じ提案の二重承認を防ぐ。
    """
    with session_factory() as session:
        idea = session.get(Idea, idea_id)
        if idea is None:
            raise IdeaNotFound("idea not found")
        target = _claim_target(idea, mode)
        updated = (
            session.query(Idea)
            .filter(Idea.id == idea_id, Idea.status == idea.status)
            .update({Idea.status: target, Idea.decided_at: idea.decided_at or datetime.now(timezone.utc)})
        )
        if updated == 0:
            raise IdeaAlreadyDecided("判断済みの提案です")
        session.commit()
        session.refresh(idea)
        return to_dict(idea)


def _update(idea_id: int, values: dict, session_factory: sessionmaker) -> dict:
    with session_factory() as session:
        idea = session.get(Idea, idea_id)
        for key, value in values.items():
            setattr(idea, key, value)
        session.commit()
        return to_dict(idea)


def record_issue_created(idea_id: int, issue_number: int, session_factory: sessionmaker = SessionLocal) -> dict:
    values = {"status": IdeaStatus.ISSUE_CREATED, "created_issue_number": issue_number}
    return _update(idea_id, values, session_factory)


def record_subtask_created(idea_id: int, subtask_id: int, session_factory: sessionmaker = SessionLocal) -> dict:
    values = {"status": IdeaStatus.SUBTASK_CREATED, "created_subtask_id": subtask_id}
    return _update(idea_id, values, session_factory)


CLAIMED_STATES = (IdeaStatus.APPROVED_ISSUE_ONLY, IdeaStatus.APPROVED_WITH_SUBTASK)


def _release(idea: Idea) -> None:
    """承認処理中の提案を承認前の状態へ戻す

    Issue作成済みの場合はIssue作成済みに戻し、後からサブタスク作成を再実行できるようにする。
    """
    created = idea.created_issue_number is not None
    idea.status = IdeaStatus.ISSUE_CREATED if created else IdeaStatus.PROPOSED
    if not created:
        idea.decided_at = None


def release_claim(idea_id: int, session_factory: sessionmaker = SessionLocal) -> dict:
    """GitHub操作の失敗時に、承認前の状態へ戻す"""
    with session_factory() as session:
        idea = session.get(Idea, idea_id)
        _release(idea)
        session.commit()
        return to_dict(idea)


def recover_interrupted_claims(session_factory: sessionmaker = SessionLocal) -> None:
    """起動時に、前回起動中に承認処理中だった提案を承認前の状態へ戻す

    戻し方はrelease_claimと同じ規則とする。
    """
    with session_factory() as session:
        for idea in session.query(Idea).filter(Idea.status.in_(CLAIMED_STATES)).all():
            _release(idea)
        session.commit()


def target_issue_number(idea: dict) -> int | None:
    """サブタスクを作成するIssue番号（既存Issue配下の提案、またはIssue作成済み）"""
    return idea["related_issue_number"] or idea["created_issue_number"]


def _section(heading: str, text: str) -> str:
    return f"## {heading}\n\n{text}" if text else ""


def _file_list(files: list[str]) -> str:
    return "\n".join(f"- {f}" for f in files)


def _join_sections(sections: list[str]) -> str:
    return "\n\n".join(s for s in sections if s)


def compose_issue_title(idea: dict) -> str:
    """提案から作成するIssueのタイトル

    アイデアマンの提案と分かるよう接頭辞を付ける。
    """
    return f"{ISSUE_TITLE_PREFIX}{idea['title']}"


def compose_issue_body(idea: dict) -> str:
    return _join_sections([
        idea["summary"],
        _section("詳細", idea["detail"]),
        _section("根拠", idea["rationale"]),
        _section("関連ファイル", _file_list(idea["related_files"])),
        ISSUE_BODY_FOOTER.format(idea_id=idea["id"]),
    ])


def compose_subtask_instruction(idea: dict) -> str:
    return _join_sections([
        SUBTASK_INSTRUCTION_HEADER,
        _section("提案タイトル", idea["title"]),
        _section("概要", idea["summary"]),
        _section("詳細", idea["detail"]),
        _section("根拠", idea["rationale"]),
        _section("関連ファイル", _file_list(idea["related_files"])),
    ])
