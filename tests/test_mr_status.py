import pytest

from core import deploy
from core.mr_status import MrStatus, derive_mr_status


@pytest.mark.parametrize(
    ("lifecycle_state", "job_status", "merge_status", "deploying", "expected"),
    [
        ("draft", None, None, False, MrStatus.DRAFT),
        ("draft", "running", None, False, MrStatus.RESOLVING),
        ("resolved", "queued", None, False, MrStatus.RESOLVING),
        ("resolved", "succeeded", None, False, MrStatus.RESOLVED),
        ("resolved", "succeeded", "queued", False, MrStatus.MERGING),
        ("resolved", None, "running", False, MrStatus.MERGING),
        ("resolved", None, "failed", False, MrStatus.RESOLVED),
        ("merged", None, "succeeded", False, MrStatus.MERGED),
        ("merged", None, "succeeded", True, MrStatus.DEPLOYING),
        ("deployed", None, None, True, MrStatus.DEPLOYED),
        ("canceled", "running", None, False, MrStatus.CANCELED),
    ],
)
def test_derive_mr_status(lifecycle_state, job_status, merge_status, deploying, expected):
    assert derive_mr_status(lifecycle_state, job_status, merge_status, deploying) == expected


def test_is_deploy_running_follows_running_projects(monkeypatch):
    monkeypatch.setattr(deploy, "_running_project_ids", {2})

    assert (deploy.is_deploy_running(1), deploy.is_deploy_running(2)) == (False, True)
