# サブタスク: [IdeaMan] 実装ジョブ・ワーカーの状態の文字列を、状態クラスにまとめるー①

アイデアマンの提案を実装する。

## 提案タイトル

実装ジョブ・ワーカーの状態の文字列を、状態クラスにまとめる

## 概要

ExecutionJob・Workerの状態は文字列のまま複数ファイルに散らばっています。実行中の状態の組も、2か所で別々に定義されています。

## 詳細

- core/job_queue.pyにExecutionJobStatusクラスを置く。
- クラスはMergeJobStatus・IdeaJobStatusと同じ形とする。
- 状態はQUEUED/RUNNING/SUCCEEDED/FAILED/NEEDS_ATTENTION/RATE_LIMITEDとし、ACTIVE_STATESも持たせる。
- Workerの状態（idle/busy）用のWorkerStateクラスも置く。
- worker/main.py・app/routes/subtasks.py・core/mr_status.py・core/idea_context.pyの文字列をこれらのクラスに置き換える。
- _CLAIM_SQL内の文字列は、バインド引数として渡す形にする。

## 根拠

ガイドラインの「変更する可能性があるModel定義（状態のEnum定義など）は1クラスに纏める」に沿っていません。
実装ジョブの状態は文字列のまま次の箇所に直接書かれています。
- core/job_queue.py:13,16,20,136,169
- worker/main.py:94,100,105,150
- app/routes/subtasks.py:522

実行中の状態の組は2か所で別々に定義されています。
- app/routes/subtasks.py:51
- core/mr_status.py:10

ワーカーの状態も文字列のまま書かれています。
- core/job_queue.py:79,82
- worker/main.py:141,204
- worker/idea_runner.py:79

一方、マージ・アイデア出しには状態クラスがあります（core/merge_queue.py:20、core/idea_queue.py:27付近）。
ジョブの種類ごとに書き方がそろっていません。

## 関連ファイル

- core/job_queue.py:10
- core/job_queue.py:31
- worker/main.py:94
- worker/main.py:150
- app/routes/subtasks.py:51
- core/mr_status.py:10
- core/idea_context.py:18
- core/merge_queue.py:20
