from app.routes import subtasks
from core.models import Project


def _project():
    return Project(id=1, name="p", github_repo="owner/repo", repo_path="x", default_branch="master")


def test_branch_name_unique_for_same_title(monkeypatch):
    monkeypatch.setattr(subtasks, "create_worktree", lambda *a, **k: None)
    monkeypatch.setattr(subtasks, "commit_subtask_instruction", lambda *a, **k: None)
    monkeypatch.setattr(subtasks, "push_branch", lambda *a, **k: None)
    monkeypatch.setattr(subtasks, "create_draft_pr", lambda **k: {"number": 1, "url": "u"})

    branch_1, _ = subtasks._create_branch_and_draft_pr(_project(), 53, "MR一覧の項目編集", "", 1)
    branch_2, _ = subtasks._create_branch_and_draft_pr(_project(), 53, "MR内容のレイアウト編集", "", 2)

    assert branch_1 != branch_2
