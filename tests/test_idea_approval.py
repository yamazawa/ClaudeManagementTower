import pytest
from sqlalchemy.orm import sessionmaker

from core import idea_approval
from core.db import init_db, make_engine
from core.idea_approval import ApprovalMode, IdeaApprovalNotAllowed
from core.ideas import IdeaAlreadyDecided, IdeaNotFound, IdeaStatus, reject_idea, save_proposals
from core.models import Idea, IdeaJob, Project


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


def _save(session_factory, related_issue_number=None) -> int:
    proposal = {
        "category": "bug",
        "title": "t",
        "summary": "概要",
        "detail": "詳細本文",
        "rationale": "根拠本文",
        "related_files": "a.py:1\nb.py:2",
        "related_issue_number": related_issue_number,
    }
    (idea_id,) = save_proposals(1, 1, [proposal], session_factory=session_factory)
    return idea_id


@pytest.mark.parametrize(
    ("mode", "status"),
    [(ApprovalMode.ISSUE_ONLY, IdeaStatus.APPROVED_ISSUE_ONLY), (ApprovalMode.WITH_SUBTASK, IdeaStatus.APPROVED_WITH_SUBTASK)],
)
def test_claim_moves_to_approved_state(session_factory, mode, status):
    idea_id = _save(session_factory)

    idea = idea_approval.claim_idea(idea_id, mode, session_factory=session_factory)

    assert idea["status"] == status
    assert idea["decided_at"] is not None


def test_claim_twice_is_refused(session_factory):
    idea_id = _save(session_factory)
    idea_approval.claim_idea(idea_id, ApprovalMode.ISSUE_ONLY, session_factory=session_factory)

    with pytest.raises(IdeaAlreadyDecided):
        idea_approval.claim_idea(idea_id, ApprovalMode.ISSUE_ONLY, session_factory=session_factory)


def test_claim_unknown_idea(session_factory):
    with pytest.raises(IdeaNotFound):
        idea_approval.claim_idea(99, ApprovalMode.ISSUE_ONLY, session_factory=session_factory)


def test_existing_issue_idea_refuses_issue_only(session_factory):
    idea_id = _save(session_factory, related_issue_number=7)

    with pytest.raises(IdeaApprovalNotAllowed):
        idea_approval.claim_idea(idea_id, ApprovalMode.ISSUE_ONLY, session_factory=session_factory)


def test_issue_created_idea_accepts_only_subtask(session_factory):
    idea_id = _save(session_factory)
    idea_approval.claim_idea(idea_id, ApprovalMode.ISSUE_ONLY, session_factory=session_factory)
    idea_approval.record_issue_created(idea_id, 12, session_factory=session_factory)

    with pytest.raises(IdeaAlreadyDecided):
        idea_approval.claim_idea(idea_id, ApprovalMode.ISSUE_ONLY, session_factory=session_factory)
    idea = idea_approval.claim_idea(idea_id, ApprovalMode.WITH_SUBTASK, session_factory=session_factory)
    assert idea["status"] == IdeaStatus.APPROVED_WITH_SUBTASK
    assert idea_approval.target_issue_number(idea) == 12


def test_release_returns_to_proposed_before_issue_creation(session_factory):
    idea_id = _save(session_factory)
    idea_approval.claim_idea(idea_id, ApprovalMode.WITH_SUBTASK, session_factory=session_factory)

    idea = idea_approval.release_claim(idea_id, session_factory=session_factory)

    assert idea["status"] == IdeaStatus.PROPOSED
    assert idea["decided_at"] is None


def test_release_keeps_issue_created(session_factory):
    idea_id = _save(session_factory)
    idea_approval.claim_idea(idea_id, ApprovalMode.WITH_SUBTASK, session_factory=session_factory)
    idea_approval.record_issue_created(idea_id, 12, session_factory=session_factory)

    idea = idea_approval.release_claim(idea_id, session_factory=session_factory)

    assert idea["status"] == IdeaStatus.ISSUE_CREATED
    assert idea["created_issue_number"] == 12


def _status(session_factory, idea_id) -> str:
    with session_factory() as session:
        return session.get(Idea, idea_id).status


def test_recover_interrupted_claims(session_factory):
    issue_only = _save(session_factory)
    with_subtask = _save(session_factory)
    issue_created = _save(session_factory)
    untouched = _save(session_factory)
    idea_approval.claim_idea(issue_only, ApprovalMode.ISSUE_ONLY, session_factory=session_factory)
    idea_approval.claim_idea(with_subtask, ApprovalMode.WITH_SUBTASK, session_factory=session_factory)
    idea_approval.claim_idea(issue_created, ApprovalMode.ISSUE_ONLY, session_factory=session_factory)
    idea_approval.record_issue_created(issue_created, 12, session_factory=session_factory)
    idea_approval.claim_idea(issue_created, ApprovalMode.WITH_SUBTASK, session_factory=session_factory)

    idea_approval.recover_interrupted_claims(session_factory=session_factory)

    assert _status(session_factory, issue_only) == IdeaStatus.PROPOSED
    assert _status(session_factory, with_subtask) == IdeaStatus.PROPOSED
    assert _status(session_factory, issue_created) == IdeaStatus.ISSUE_CREATED
    assert _status(session_factory, untouched) == IdeaStatus.PROPOSED


def test_recover_keeps_decided_ideas(session_factory):
    rejected = _save(session_factory)
    reject_idea(rejected, "不要", session_factory=session_factory)
    subtask_created = _save(session_factory, related_issue_number=7)
    idea_approval.claim_idea(subtask_created, ApprovalMode.WITH_SUBTASK, session_factory=session_factory)
    idea_approval.record_subtask_created(subtask_created, 3, session_factory=session_factory)

    idea_approval.recover_interrupted_claims(session_factory=session_factory)

    assert _status(session_factory, rejected) == IdeaStatus.REJECTED
    assert _status(session_factory, subtask_created) == IdeaStatus.SUBTASK_CREATED


def test_record_subtask_created(session_factory):
    idea_id = _save(session_factory, related_issue_number=7)
    idea_approval.claim_idea(idea_id, ApprovalMode.WITH_SUBTASK, session_factory=session_factory)

    idea = idea_approval.record_subtask_created(idea_id, 3, session_factory=session_factory)

    assert idea["status"] == IdeaStatus.SUBTASK_CREATED
    assert idea["created_subtask_id"] == 3
    assert idea_approval.target_issue_number(idea) == 7


def test_compose_issue_title_adds_prefix():
    assert idea_approval.compose_issue_title({"title": "提案"}) == "[IdeaMan] 提案"


def test_compose_issue_body(session_factory):
    idea = idea_approval.claim_idea(_save(session_factory), ApprovalMode.ISSUE_ONLY, session_factory=session_factory)

    body = idea_approval.compose_issue_body(idea)

    assert body.startswith("概要")
    assert "## 根拠\n\n根拠本文" in body
    assert "- a.py:1\n- b.py:2" in body
    assert body.endswith(f"アイデアマンの提案（ID: {idea['id']}）から作成")


def test_compose_subtask_instruction_skips_empty_sections(session_factory):
    idea = idea_approval.claim_idea(_save(session_factory), ApprovalMode.WITH_SUBTASK, session_factory=session_factory)
    idea["detail"] = ""

    instruction = idea_approval.compose_subtask_instruction(idea)

    assert instruction.startswith("アイデアマンの提案を実装する。")
    assert "## 提案タイトル\n\nt" in instruction
    assert "## 詳細" not in instruction
