# サブタスク: [IdeaMan] 実装ジョブが実行中・待機中のMRに対して、実装の再実行を受け付けないー①

アイデアマンの提案を実装する。

## 提案タイトル

実装ジョブが実行中・待機中のMRに対して、実装の再実行を受け付けない

## 概要

実装実行APIは、同じMRのジョブが待機中・実行中でも新しいジョブを登録します。2つの端末から操作すると、同じ指示が二重に実行されます。

## 詳細

- execute_subtaskで_has_active_job（同ファイル内に既存）を使い、実行中・待機中なら409を返す。
- 画面側は409を受けたら、既存ジョブのポーリングに切り替える。
- あわせて、既存ジョブが実行中であることを表示する。
- 同じMRへの連続実行で2件目が拒否されることをテストする。

## 根拠

app/routes/subtasks.py:509-527のexecute_subtaskは、マージ待ちだけを確認しています。
そのうえで、常にExecutionJob(status='queued')を追加します。
同じファイルの_has_active_job（app/routes/subtasks.py:414-421）は、マージ可否の判定にしか使われていません。
画面側の二重実行防止はブラウザ内の状態だけで行われています（app/static/job_runner.js:19、busySubtaskIds）。
そのため、別の端末や再読み込み後の画面からは再送できます。
core/job_queue.py:10-27の取得SQLは同時実行を防ぎますが、待機中の2件目は1件目の完了後に実行されます。

## 関連ファイル

- app/routes/subtasks.py:509
- app/routes/subtasks.py:414
- app/static/job_runner.js:12
- core/job_queue.py:10
