# サブタスク: [SPn]タスクn - 5時間枠の上限中はジョブを取得せず、リセット後に再開するー①

アイデアマンの提案を実装する。

## 提案タイトル

[SPn]タスクn - 5時間枠の上限中はジョブを取得せず、リセット後に再開する

## 概要

Claudeの利用上限に達していてもワーカーがジョブを取得し、ジョブが即座に失敗しています。上限中は取得を止め、上限で失敗したジョブはリセット後に再投入できるようにします。

## 詳細

_process_next_jobで、rate_limit_snapshotsの状態が上限（rejected等）でresets_atが未来なら、ジョブを取得せず待機します。
Claudeの結果が「hit your limit」系のエラーだった場合は、failedと区別する状態（needs_attention等）にします。
リセット後に自動で再投入するか、画面から再実行を促すかは要検討です。
アイデア出しジョブ（claim_next_idea_job）にも同じ判定を入れます。

## 根拠

#165 Issueフィルタの修正ー①が「You've hit your 5-hour limit · resets 10pm (exit code: 1)」でfailedになっています。
worker/main.py:159-173は、利用上限の状態を確認せずにジョブを取得しています。
core/rate_limits.py:23-42でstatusとresets_atを保存していますが、画面表示（get_rate_limits）にしか使っていません。

## 関連ファイル

- worker/main.py:159
- worker/main.py:123
- core/rate_limits.py:23
- core/models.py:192
## 実行指示（2026-11-23 00:58:10 UTC）

アイデアマンの提案を実装する。

## 提案タイトル

[SPn]タスクn - 5時間枠の上限中はジョブを取得せず、リセット後に再開する

## 概要

Claudeの利用上限に達していてもワーカーがジョブを取得し、ジョブが即座に失敗しています。上限中は取得を止め、上限で失敗したジョブはリセット後に再投入できるようにします。

## 詳細

_process_next_jobで、rate_limit_snapshotsの状態が上限（rejected等）でresets_atが未来なら、ジョブを取得せず待機します。
Claudeの結果が「hit your limit」系のエラーだった場合は、failedと区別する状態（needs_attention等）にします。
リセット後に自動で再投入するか、画面から再実行を促すかは要検討です。
アイデア出しジョブ（claim_next_idea_job）にも同じ判定を入れます。

## 根拠

#165 Issueフィルタの修正ー①が「You've hit your 5-hour limit · resets 10pm (exit code: 1)」でfailedになっています。
worker/main.py:159-173は、利用上限の状態を確認せずにジョブを取得しています。
core/rate_limits.py:23-42でstatusとresets_atを保存していますが、画面表示（get_rate_limits）にしか使っていません。

## 関連ファイル

- worker/main.py:159
- worker/main.py:123
- core/rate_limits.py:23
- core/models.py:192

