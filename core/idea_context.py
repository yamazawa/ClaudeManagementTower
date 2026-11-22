"""アイデア出しジョブへの指示文

Claudeは読み取り専用でGitHubやDBを参照できないため、
Open Issue・過去の実行履歴・既存の提案は管理塔側で集めて指示文に含める。
"""

import json
from collections.abc import Callable

from sqlalchemy.orm import sessionmaker

from core.db import SessionLocal
from core.github_client import GitHubClientError, list_issues
from core.ideas import IdeaCategory, IdeaStatus
from core.models import ExecutionEvent, ExecutionJob, Idea, Project, Report, Subtask

# 要確認・失敗として扱う実行ジョブの状態
FAILED_JOB_STATES = ("failed", "needs_attention")
EXCERPT_MAX_LENGTH = 500
NONE_TEXT = "（なし）"
ISSUE_FETCH_FAILED_TEXT = "（取得に失敗したため不明。重複に注意する）"

OUTPUT_FORMAT_TEXT = """
# 出力形式
調査結果を最終応答の最後に、次の形式のJSON配列で ```json ～ ``` に囲んで出力する。
提案が無い場合は空配列 [] を出力する。
- category : {categories} のいずれか
- title : Issueタイトル案
- summary : 提案の要約（1～2文）
- detail : 対応内容の案
- rationale : 根拠（対象ファイル・行・観測した事象）
- related_files : 関連ファイルの配列（"パス:行" 形式）
- related_issue_number : 既存Open Issue配下のサブタスク案の場合はそのIssue番号、新規Issue案はnull
"""


def _excerpt(text: str | None) -> str:
    return " ".join((text or "").split())[:EXCERPT_MAX_LENGTH]


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) if lines else NONE_TEXT


def _open_issue_lines(repo: str, issue_lister: Callable[[str], list[dict]]) -> str:
    try:
        issues = issue_lister(repo)
    except GitHubClientError:
        return ISSUE_FETCH_FAILED_TEXT
    return _bullets([f"#{i['number']} {i['title']}" for i in issues])


def _last_error(session, job_id: int) -> str:
    event = (
        session.query(ExecutionEvent)
        .filter(ExecutionEvent.job_id == job_id, ExecutionEvent.event_type == "error")
        .order_by(ExecutionEvent.sequence_no.desc())
        .first()
    )
    return _excerpt(event.content) if event else ""


def _failed_job_lines(session, project_id: int, limit: int) -> str:
    rows = (
        session.query(ExecutionJob, Subtask)
        .join(Subtask, ExecutionJob.subtask_id == Subtask.id)
        .filter(Subtask.project_id == project_id, ExecutionJob.status.in_(FAILED_JOB_STATES))
        .order_by(ExecutionJob.id.desc())
        .limit(limit)
        .all()
    )
    return _bullets(
        [f"#{s.github_issue_number} {s.title}（{j.status}）{_last_error(session, j.id)}" for j, s in rows]
    )


def _report_lines(session, project_id: int, limit: int) -> str:
    rows = (
        session.query(Report, Subtask)
        .join(ExecutionJob, Report.job_id == ExecutionJob.id)
        .join(Subtask, ExecutionJob.subtask_id == Subtask.id)
        .filter(Subtask.project_id == project_id)
        .order_by(Report.id.desc())
        .limit(limit)
        .all()
    )
    return _bullets([f"#{s.github_issue_number} {s.title}: {_excerpt(r.summary)}" for r, s in rows])


def _idea_lines(session, project_id: int, statuses: tuple[str, ...], limit: int) -> str:
    ideas = (
        session.query(Idea)
        .filter(Idea.project_id == project_id, Idea.status.in_(statuses))
        .order_by(Idea.id.desc())
        .limit(limit)
        .all()
    )
    return _bullets([f"{i.title}" + (f"（却下理由: {i.reject_reason}）" if i.reject_reason else "") for i in ideas])


def _history_sections(session, project_id: int, limit: int) -> list[str]:
    return [
        "# 最近失敗・要確認になった実行\n" + _failed_job_lines(session, project_id, limit),
        "# 最近の実行レポートの要約\n" + _report_lines(session, project_id, limit),
        "# 未処理・承認済みの提案（重複させない）\n"
        + _idea_lines(session, project_id, IdeaStatus.PENDING_STATES + IdeaStatus.APPROVED_STATES, limit),
        "# 却下された提案（同じ趣旨で再提案しない）\n"
        + _idea_lines(session, project_id, IdeaStatus.REJECTED_STATES, limit),
    ]


def build_idea_prompt(
    project_id: int,
    max_proposals: int,
    history_limit: int,
    session_factory: sessionmaker = SessionLocal,
    issue_lister: Callable[[str], list[dict]] = list_issues,
) -> str:
    """アイデア出しの指示文を組み立てる"""
    with session_factory() as session:
        project = session.get(Project, project_id)
        history = _history_sections(session, project_id, history_limit)
    header = (
        f"リポジトリ {project.github_repo} のコード・ドキュメントを調査し、"
        f"改善提案（Issue案・サブタスク案）を最大{max_proposals}件出してください。"
    )
    sections = [header, "# Open Issue一覧（重複させない）\n" + _open_issue_lines(project.github_repo, issue_lister)]
    output_format = OUTPUT_FORMAT_TEXT.format(categories=json.dumps(list(IdeaCategory.ALL)))
    return "\n\n".join([*sections, *history, output_format.strip()])
