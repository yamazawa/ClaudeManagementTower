"""リポジトリ一覧からのリポジトリ追加

ローカル作成・GitHub登録・管理塔への登録を順に行う。
続けて管理用の初期設定をIssue・MRで行う（core/repo_initial_setup.py）。
作成済みのフォルダ・GitHubリポジトリは、途中で失敗しても削除しない。
"""

import re
from dataclasses import dataclass
from pathlib import Path

from core.config import settings
from core.db import SessionLocal
from core.git_client import GitClientError, commit_files, init_local_repo
from core.github_client import GitHubClientError, create_repo_from_local
from core.models import Project
from core.repo_initial_setup import run_initial_setup

# 英語名（フォルダ名・GitHubのリポジトリ名）に使える文字
REPO_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
DEFAULT_BRANCH = "master"
README_PATH = "README.md"
INITIAL_COMMIT_MESSAGE = "Initial commit"


class RepoSetupError(RuntimeError):
    """リポジトリ追加の失敗

    project_idは、管理塔への登録まで済んだ場合のリポジトリID。
    """

    def __init__(self, message: str, project_id: int | None = None):
        super().__init__(message)
        self.project_id = project_id


class RepoValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NewRepo:
    name: str
    display_name: str
    description: str

    @property
    def github_repo(self) -> str:
        owner = settings.new_repo_owner or settings.self_repo.split("/")[0]
        return f"{owner}/{self.name}"

    @property
    def repo_path(self) -> str:
        return f"{settings.new_repo_base_dir}/{self.name}"


def normalize_new_repo(name: str, display_name: str, description: str) -> NewRepo:
    """入力値の前後の空白を除き、必須・文字種を確認する"""
    repo = NewRepo(name.strip(), display_name.strip(), description.strip())
    if not REPO_NAME_PATTERN.match(repo.name):
        raise RepoValidationError("英語名は英数字・「.」「_」「-」で入力してください（先頭は英数字）")
    if not repo.display_name:
        raise RepoValidationError("日本語名を入力してください")
    if not repo.description:
        raise RepoValidationError("何をするPJかを入力してください")
    return repo


def ensure_not_exists(session, repo: NewRepo) -> None:
    """作成先のフォルダ・管理塔への登録が既に無いか確認する"""
    if Path(repo.repo_path).exists():
        raise RepoValidationError(f"{repo.repo_path} は既に存在します")
    registered = session.query(Project).filter_by(github_repo=repo.github_repo).first()
    if registered is not None:
        raise RepoValidationError(f"{repo.github_repo} は既に登録されています")


def create_repository(repo: NewRepo, session_factory=None) -> dict:
    """リポジトリを作成して管理塔に登録し、初期設定のIssue・MRを完了させる

    入力の不備はRepoValidationError、作成途中の失敗はRepoSetupErrorとする。
    """
    factory = session_factory or SessionLocal
    with factory() as session:
        ensure_not_exists(session, repo)
    try:
        _create_local_and_github_repo(repo)
    except (GitClientError, GitHubClientError, OSError) as exc:
        raise RepoSetupError(f"リポジトリの作成に失敗しました: {exc}") from exc
    project_id = _register_project(factory, repo)
    try:
        setup = run_initial_setup(project_id, factory)
    except (GitClientError, GitHubClientError) as exc:
        message = f"リポジトリを登録しましたが、初期設定のIssue・MRに失敗しました: {exc}"
        raise RepoSetupError(message, project_id) from exc
    return {"project_id": project_id, **setup}


def _create_local_and_github_repo(repo: NewRepo) -> None:
    """ローカルに最初のコミットを作り、GitHubへ登録してpushする

    初期設定のMRを作るため、既定ブランチにREADMEだけをコミットしておく。
    """
    init_local_repo(repo.repo_path, DEFAULT_BRANCH)
    Path(repo.repo_path, README_PATH).write_text(_readme(repo), encoding="utf-8")
    commit_files(repo.repo_path, [README_PATH], INITIAL_COMMIT_MESSAGE)
    create_repo_from_local(
        repo.github_repo, repo.repo_path, repo.description, settings.new_repo_visibility
    )


def _readme(repo: NewRepo) -> str:
    return f"# {repo.display_name}\n\n{repo.description}\n"


def _register_project(factory, repo: NewRepo) -> int:
    with factory() as session:
        project = Project(
            name=repo.name,
            github_repo=repo.github_repo,
            repo_path=repo.repo_path,
            default_branch=DEFAULT_BRANCH,
            display_name=repo.display_name,
            description=repo.description,
        )
        session.add(project)
        session.commit()
        return project.id
