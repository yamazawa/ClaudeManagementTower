# サブタスク: [IdeaMan] サーバー・ワーカーのログ出力をloggingにそろえ、時刻を付けるー①

アイデアマンの提案を実装する。

## 提案タイトル

サーバー・ワーカーのログ出力をloggingにそろえ、時刻を付ける

## 概要

ログはprintとloggingが混在していて、logging側の出力設定もありません。失敗の発生時刻が残らず、障害の原因を後から追いにくくなっています。

## 詳細

- サーバー起動時（app/main.pyのlifespan）とワーカー起動時（worker/main.pyのmain）にlogging.basicConfigを設定する。
- 出力形式は時刻・ロガー名・レベル付きとする。
- worker・core配下のprintをlogger.info/warningに置き換える。
- 既存の[worker]等の接頭辞は、ロガー名で代用する。
- 必要に応じて、ファイルへの出力やローテーションも設定項目として検討する。

## 根拠

app・core・worker配下にはlogging.basicConfigがありません。
そのため、logger.warningは時刻なしで標準エラーに出ます。
logger.warningの使用箇所は次のとおりです。
- core/merge_queue.py:163,177
- core/cli_session.py:369
- core/subtask_rollback.py:72
- core/github_client.py:266

logger.infoは出力されません。
一方、同じ種類の失敗ログをprintで出している箇所もあります。
- core/pr_sync.py:147,183
- core/deploy.py:190
- core/claude_usage.py:134

ワーカーのログはprintのみです（worker/main.py 10か所、worker/pool.py 3か所、worker/idea_runner.py 2か所）。
#153 では、TLSタイムアウト・バッファ超過による失敗が短期間に何度も起きています。
時刻付きのログが無いと、ジョブ・同期処理・マージ処理の時系列を突き合わせにくくなります。

## 関連ファイル

- app/main.py:22
- worker/main.py:232
- worker/pool.py:88
- core/pr_sync.py:147
- core/deploy.py:190
- core/claude_usage.py:134
- core/merge_queue.py:163
## 実行指示（2026-11-23 23:00:30 UTC）

アイデアマンの提案を実装する。

## 提案タイトル

サーバー・ワーカーのログ出力をloggingにそろえ、時刻を付ける

## 概要

ログはprintとloggingが混在していて、logging側の出力設定もありません。失敗の発生時刻が残らず、障害の原因を後から追いにくくなっています。

## 詳細

- サーバー起動時（app/main.pyのlifespan）とワーカー起動時（worker/main.pyのmain）にlogging.basicConfigを設定する。
- 出力形式は時刻・ロガー名・レベル付きとする。
- worker・core配下のprintをlogger.info/warningに置き換える。
- 既存の[worker]等の接頭辞は、ロガー名で代用する。
- 必要に応じて、ファイルへの出力やローテーションも設定項目として検討する。

## 根拠

app・core・worker配下にはlogging.basicConfigがありません。
そのため、logger.warningは時刻なしで標準エラーに出ます。
logger.warningの使用箇所は次のとおりです。
- core/merge_queue.py:163,177
- core/cli_session.py:369
- core/subtask_rollback.py:72
- core/github_client.py:266

logger.infoは出力されません。
一方、同じ種類の失敗ログをprintで出している箇所もあります。
- core/pr_sync.py:147,183
- core/deploy.py:190
- core/claude_usage.py:134

ワーカーのログはprintのみです（worker/main.py 10か所、worker/pool.py 3か所、worker/idea_runner.py 2か所）。
#153 では、TLSタイムアウト・バッファ超過による失敗が短期間に何度も起きています。
時刻付きのログが無いと、ジョブ・同期処理・マージ処理の時系列を突き合わせにくくなります。

## 関連ファイル

- app/main.py:22
- worker/main.py:232
- worker/pool.py:88
- core/pr_sync.py:147
- core/deploy.py:190
- core/claude_usage.py:134
- core/merge_queue.py:163

