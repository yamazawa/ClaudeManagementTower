import pytest
from sqlalchemy.orm import sessionmaker

from core.db import init_db, make_engine
from core.github_client import GitHubClientError
from core.idea_context import ISSUE_FETCH_FAILED_TEXT, build_idea_prompt
from core.ideas import IdeaStatus
from core.models import ExecutionEvent, ExecutionJob, Idea, IdeaJob, Project, Report, Subtask


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Project(id=1, name="p", github_repo="owner/repo", repo_path="C:/repo", default_branch="master"))
        session.add(
            Subtask(
                id=1, project_id=1, github_issue_number=3, title="ログ出力の改善",
                instruction="i", branch_name="b", lifecycle_state="draft",
            )
        )
        session.add(ExecutionJob(id=1, subtask_id=1, status="failed"))
        session.add(ExecutionJob(id=2, subtask_id=1, status="succeeded"))
        session.add(ExecutionEvent(job_id=1, sequence_no=1, event_type="error", content="gh がタイムアウトしました"))
        session.add(Report(job_id=2, html_path="r.html", summary="テストを追加した"))
        session.add(IdeaJob(id=1, project_id=1, status="succeeded"))
        session.add(_idea("却下済の案", IdeaStatus.REJECTED, reject_reason="対応済み"))
        session.add(_idea("未処理の案", IdeaStatus.PROPOSED))
        session.commit()
    return factory


def _idea(title, status, reject_reason=None):
    return Idea(
        project_id=1, source_job_id=1, category="bug", title=title, summary="", detail="",
        rationale="", related_files="", status=status, reject_reason=reject_reason,
    )


def _build(session_factory, issue_lister):
    return build_idea_prompt(1, 5, 10, session_factory=session_factory, issue_lister=issue_lister)


def test_prompt_includes_issues_history_and_ideas(session_factory):
    prompt = _build(session_factory, lambda repo: [{"number": 9, "title": "既存のIssue"}])

    assert "owner/repo" in prompt
    assert "最大5件" in prompt
    assert "#9 既存のIssue" in prompt
    assert "#3 ログ出力の改善（failed）gh がタイムアウトしました" in prompt
    assert "#3 ログ出力の改善: テストを追加した" in prompt
    assert "未処理の案" in prompt
    assert "却下済の案（却下理由: 対応済み）" in prompt
    assert "```json" in prompt


def test_prompt_marks_issue_fetch_failure(session_factory):
    def failing_lister(repo):
        raise GitHubClientError("auth")

    assert ISSUE_FETCH_FAILED_TEXT in _build(session_factory, failing_lister)


def test_prompt_shows_none_for_empty_issue_list(session_factory):
    assert "# Open Issue一覧（重複させない）\n（なし）" in _build(session_factory, lambda repo: [])
