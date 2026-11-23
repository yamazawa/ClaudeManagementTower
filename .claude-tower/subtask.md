# サブタスク: [IdeaMan] ワーカーのジョブ処理で想定外の例外が起きても、ワーカーを停止させないー①

アイデアマンの提案を実装する。

## 提案タイトル

ワーカーのジョブ処理で想定外の例外が起きても、ワーカーを停止させない

## 概要

ワーカーで想定外の例外が起きると、プロセスが落ちます。対象ジョブは失敗理由が残らないまま、ハートビート途絶まで実行中に残ります。

## 詳細

- process_jobの前処理（set_worker_state・_load_subtask_and_project・record_event）をtryの中に移す。
- 失敗はfailedとして実際のエラー内容を記録する。
- run_loopの1周分を例外で保護する。
- _merge_loopと同じく、ログを出して次の周回へ進む。
- サブタスク・プロジェクトが削除済みの場合のテストを追加する。
- DB一時エラーでループが継続することのテストも追加する。

## 根拠

worker/main.py:141-144の前処理はtryの外にあります。
そのため、サブタスクが見つからないときのAttributeErrorはrun_loopまで伝わり、ワーカーが終了します。
run_loop（worker/main.py:203-210）には例外の保護がありません。
_cleanup_stale_recordsでのDBロック等でも同じくワーカーが終了します。
一方、core/merge_queue.py:172-177の_merge_loopは「DBの一時的な失敗で処理スレッドを止めない」として例外を保護しています。
ワーカーが落ちると、ジョブはstatus=runningのまま残ります。
その後、job_stale_timeout後にneeds_attentionになります（core/job_queue.py:123-139）。
記録される理由は「ワーカーからの応答が途絶えたため中断しました」だけで、本当の原因が残りません。

## 関連ファイル

- worker/main.py:134
- worker/main.py:197
- worker/main.py:125
- core/merge_queue.py:170
- core/job_queue.py:123
- worker/pool.py:97
