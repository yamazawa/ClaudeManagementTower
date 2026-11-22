import pytest
from sqlalchemy.orm import sessionmaker

from core import ideas
from core.db import init_db, make_engine
from core.ideas import IdeaCategory, IdeaStatus
from core.models import IdeaJob, Project


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Project(id=1, name="p", github_repo="owner/repo", repo_path="C:/repo", default_branch="master"))
        session.add(IdeaJob(id=1, project_id=1, status="succeeded"))
        session.commit()
    return factory


def _proposal(title="t", **overrides):
    return {
        "category": "bug",
        "title": title,
        "summary": "s",
        "detail": "d",
        "rationale": "r",
        "related_files": "a.py:1",
        "related_issue_number": None,
        **overrides,
    }


def test_parse_proposals_reads_json_block():
    text = '調査しました。\n```json\n[{"title": "重複処理の共通化", "category": "refactor", "related_files": ["core/a.py:10"]}]\n```'

    result = ideas.parse_proposals(text, max_count=5)

    assert result[0]["title"] == "重複処理の共通化"
    assert result[0]["category"] == IdeaCategory.REFACTOR
    assert result[0]["related_files"] == "core/a.py:10"
    assert result[0]["related_issue_number"] is None


def test_parse_proposals_accepts_bare_json_array():
    assert ideas.parse_proposals('[{"title": "x"}]', max_count=5)[0]["title"] == "x"


def test_parse_proposals_normalizes_unknown_values():
    text = '[{"title": "x", "category": "unknown", "related_issue_number": "12"}, {"summary": "no title"}, "bad"]'

    result = ideas.parse_proposals(text, max_count=5)

    assert len(result) == 1
    assert result[0]["category"] == IdeaCategory.FEATURE
    assert result[0]["related_issue_number"] is None


def test_parse_proposals_keeps_existing_issue_number():
    assert ideas.parse_proposals('[{"title": "x", "related_issue_number": 7}]', 5)[0]["related_issue_number"] == 7


def test_parse_proposals_limits_count():
    text = "[" + ",".join(f'{{"title": "t{i}"}}' for i in range(8)) + "]"

    assert [p["title"] for p in ideas.parse_proposals(text, max_count=3)] == ["t0", "t1", "t2"]


def test_parse_proposals_rejects_invalid_json():
    with pytest.raises(ideas.IdeaParseError):
        ideas.parse_proposals("提案はありません", max_count=5)


def test_parse_proposals_rejects_non_array():
    with pytest.raises(ideas.IdeaParseError):
        ideas.parse_proposals('{"title": "x"}', max_count=5)


def test_save_and_list_proposals(session_factory):
    ids = ideas.save_proposals(1, 1, [_proposal("a"), _proposal("b")], session_factory=session_factory)

    listed = ideas.list_ideas(1, session_factory=session_factory)

    assert [i["id"] for i in listed] == list(reversed(ids))
    assert listed[0]["status"] == IdeaStatus.PROPOSED
    assert listed[0]["related_files"] == ["a.py:1"]


def test_list_ideas_filters_by_status(session_factory):
    first, _ = ideas.save_proposals(1, 1, [_proposal("a"), _proposal("b")], session_factory=session_factory)
    ideas.reject_idea(first, "不要", session_factory=session_factory)

    pending = ideas.list_ideas(1, IdeaStatus.PENDING_STATES, session_factory=session_factory)
    rejected = ideas.list_ideas(1, IdeaStatus.REJECTED_STATES, session_factory=session_factory)

    assert [i["title"] for i in pending] == ["b"]
    assert [i["title"] for i in rejected] == ["a"]
    assert rejected[0]["reject_reason"] == "不要"
    assert rejected[0]["decided_at"] is not None


def test_reject_idea_twice_is_refused(session_factory):
    (idea_id,) = ideas.save_proposals(1, 1, [_proposal()], session_factory=session_factory)
    ideas.reject_idea(idea_id, "", session_factory=session_factory)

    with pytest.raises(ideas.IdeaAlreadyDecided):
        ideas.reject_idea(idea_id, "", session_factory=session_factory)


def test_reject_unknown_idea(session_factory):
    with pytest.raises(ideas.IdeaNotFound):
        ideas.reject_idea(99, "", session_factory=session_factory)
