"""APIのエラーメッセージ定義

HTTPExceptionのdetailに設定する画面表示用の文言を集約する。
"""

PROJECT_NOT_FOUND = "プロジェクトが見つかりません"
SUBTASK_NOT_FOUND = "MRが見つかりません"
JOB_NOT_FOUND = "ジョブが見つかりません"
REPORT_NOT_FOUND = "レポートが見つかりません"
ATTACHMENT_NOT_FOUND = "添付ファイルが見つかりません"
DEPLOY_RESULT_NOT_FOUND = "デプロイの実行結果がありません"
SELF_SYNC_RESULT_NOT_FOUND = "マージして最新化の実行結果がありません"

TITLE_EMPTY = "タイトルが空です"
ISSUE_TITLE_EMPTY = "Issueタイトルが空です"
TEXT_EMPTY = "入力内容が空です"

NOT_SUPERVISED = "run_all.py経由で起動していないため実行できません"
UNRESOLVED_MR_REMAINS = "未解決のMRが残っています"
NOT_UNLINKED_MR = "Issue未紐付けのMRではありません"
NOT_UNRESOLVED_MR = "未解決のMRではありません"
NOT_CLOSED_MR = "クローズ済のMRではありません"
NOT_RESOLVED_MR = "ResolvedのMRではありません"
PR_NOT_CREATED = "PRが作成されていません"
MERGE_BLOCKED_BY_ACTIVE_JOB = "実装の実行中はマージできません"
ALREADY_IN_MERGE_QUEUE = "マージ待ちに登録済です"
EXECUTE_BLOCKED_BY_MERGE_QUEUE = "マージ待ちのMRは実装できません"
JOB_ACTIVE = "実装の実行中・実行待ちです"
WORKTREE_MISSING = "worktreeがありません"

ISSUE_CREATE_FAILED = "Issue作成に失敗しました: {reason}"
SUBTASK_CREATE_FAILED = "サブタスク作成に失敗しました: {reason}"
