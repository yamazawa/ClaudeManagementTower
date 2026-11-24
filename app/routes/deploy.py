from fastapi import APIRouter, HTTPException

from app.routes.lookups import get_project_or_404
from app.routes.system import NOT_SUPERVISED_DETAIL
from core.db import SessionLocal
from core.deploy import (
    DeployAlreadyRunning,
    DeployError,
    DeployNotDefined,
    finish_without_steps,
    is_deploy_defined,
    load_steps,
    pull_branch,
    read_result,
    restart_commands,
    start_deploy,
)
from core.git_client import GitClientError, has_remote_updates
from core.supervisor_control import is_supervised

router = APIRouter(prefix="/api/projects")


def _get_project(project_id: int) -> tuple[str, str]:
    with SessionLocal() as session:
        project = get_project_or_404(session, project_id)
        return project.repo_path, project.default_branch


def _load_steps_or_error(repo_path: str) -> list[dict]:
    try:
        return load_steps(repo_path)
    except DeployNotDefined as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DeployError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{project_id}/deploy", status_code=202)
def deploy_project(project_id: int) -> dict:
    """リポジトリに定義したデプロイ手順を別スレッドで開始する

    再起動を含む手順はrun_all.py経由で起動している場合のみ実行できる。
    デプロイ未定義のリポジトリは、手順を実行せずマージ済MRをDeployedにする。
    """
    repo_path, branch = _get_project(project_id)
    if not is_deploy_defined(repo_path):
        finish_without_steps(project_id)
        return {"accepted": True, "restarts": [], "skipped": True}
    steps = _load_steps_or_error(repo_path)
    restarts = restart_commands(steps)
    if restarts and not is_supervised():
        raise HTTPException(status_code=409, detail=NOT_SUPERVISED_DETAIL)
    try:
        start_deploy(project_id, repo_path, branch, steps)
    except DeployAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"accepted": True, "restarts": restarts}


@router.get("/{project_id}/deploy/pending")
def get_deploy_pending(project_id: int) -> dict:
    """デプロイ先のソースに未取り込みの対応があるかを返す

    デプロイ手順のpullで取り込むブランチを、チェックアウト中のHEADと比較する。
    デプロイ未定義・pull手順なしの場合は未取り込みなしとする。
    """
    repo_path, default_branch = _get_project(project_id)
    try:
        branch = pull_branch(load_steps(repo_path), default_branch)
    except DeployError:
        return {"pending": False}
    if branch is None:
        return {"pending": False}
    try:
        return {"pending": has_remote_updates(repo_path, branch)}
    except GitClientError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{project_id}/deploy")
def get_deploy_result(project_id: int) -> dict:
    result = read_result(project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="デプロイの実行結果がありません")
    return result
