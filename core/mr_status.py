"""MRの表示ステータス

画面の表示ステータス（app/static/common.jsのMR_STATUS、subtask_view.jsのmrStatus）と値・導出方法を合わせる。
"""

from core.job_queue import ExecutionJobStatus
from core.lifecycle import LifecycleState
from core.merge_queue import MergeJobStatus


class MrStatus:
    """MRの表示ステータス

    RESOLVING : 未解決のMRで実装ジョブが実行中
    MERGING : ResolvedのMRがマージ待ち・マージ中
    DEPLOYING : MergedのMRのリポジトリでデプロイ実行中
    その他はlifecycle_stateと同じ値とする。
    """

    DRAFT = LifecycleState.DRAFT
    RESOLVING = "resolving"
    RESOLVED = LifecycleState.RESOLVED
    MERGING = "merging"
    MERGED = LifecycleState.MERGED
    DEPLOYING = "deploying"
    DEPLOYED = LifecycleState.DEPLOYED
    CANCELED = LifecycleState.CANCELED

    # ヘッダーのステータスフィルタで数える状態（表示順）
    COUNTED = (DRAFT, RESOLVING, RESOLVED, MERGING, MERGED, DEPLOYING, DEPLOYED)


def derive_mr_status(
    lifecycle_state: str,
    job_status: str | None,
    merge_status: str | None,
    deploying: bool,
) -> str:
    """lifecycle_stateと実行中の処理から表示ステータスを導出する

    job_status・merge_statusは最新の実装ジョブ・マージ待ち行列の状態とする。
    deployingはMRのリポジトリでデプロイ実行中かを表す。
    """
    if lifecycle_state in LifecycleState.OPEN_STATES and job_status in ExecutionJobStatus.ACTIVE_STATES:
        return MrStatus.RESOLVING
    if lifecycle_state == LifecycleState.RESOLVED and merge_status in MergeJobStatus.ACTIVE_STATES:
        return MrStatus.MERGING
    if lifecycle_state == LifecycleState.MERGED and deploying:
        return MrStatus.DEPLOYING
    return lifecycle_state
