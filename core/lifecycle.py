"""MR（サブタスク）のlifecycle_state定義

画面のフィルタ・ボタン定義（app/static/app.js）と値を合わせる。
"""


class LifecycleState:
    """MRの状態

    DRAFT : PRがドラフト
    RESOLVED : PRのドラフトが外れた
    MERGED : マージ済（デプロイ待ち）
    DEPLOYED : マージ済で、デプロイしたソースに含まれる
    CANCELED : マージせずクローズ済

    Resolving（実装中）・Merging（マージ中）・Deploying（デプロイ中）は保存しない。
    lifecycle_stateと実行中の処理から導出する（core/mr_status.py）。
    """

    DRAFT = "draft"
    RESOLVED = "resolved"
    MERGED = "merged"
    DEPLOYED = "deployed"
    CANCELED = "canceled"

    # 未解決（Issueクローズを妨げる・Cancel可能）の状態
    OPEN_STATES = (DRAFT, RESOLVED)
    # マージ済（解決済）の状態
    MERGED_STATES = (MERGED, DEPLOYED)
