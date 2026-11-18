"""MR（サブタスク）のlifecycle_state定義

画面のフィルタ・ボタン定義（app/static/app.js）と値を合わせる。
"""


class LifecycleState:
    """MRの状態

    DRAFT : PRがドラフト
    RESOLVED : PRのドラフトが外れた
    MERGED : マージ済
    CANCELED : マージせずクローズ済
    """

    DRAFT = "draft"
    RESOLVED = "resolved"
    MERGED = "merged"
    CANCELED = "canceled"

    # 未解決（Issueクローズを妨げる・Cancel可能）の状態
    OPEN_STATES = (DRAFT, RESOLVED)
