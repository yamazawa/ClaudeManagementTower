# サブタスク: [IdeaMan] 実装ジョブ・アイデア出しジョブに最大実行時間を設け、超えたら要確認にするー①

アイデアマンの提案を実装する。

## 提案タイトル

実装ジョブ・アイデア出しジョブに最大実行時間を設け、超えたら要確認にする

## 概要

Claude実行に上限時間が無く、Claudeが応答しなくなるとワーカーが手動で止めるまで占有されます。上限時間を設定項目に追加し、超えたら打ち切って要確認にします。

## 詳細

- config.pyに、実装ジョブ用とアイデア出し用の最大実行時間を追加する。
- worker/main.pyの_run_claude_for_jobとidea_runner._executeで、Claude実行をasyncio.wait_forで包む。
- 上限を超えたら、実装ジョブはneeds_attention、アイデア出しジョブはfailedにする。
- 打ち切った理由をイベントとエラーメッセージに残す。
- 上限超過時の状態遷移をテストで確認する。

## 根拠

worker/main.py:69とworker/idea_runner.py:47は、asyncio.runでClaudeの終了を上限なしに待っている。worker/heartbeat.py:16-18は実行中にハートビートを送り続けるため、recover_stale_jobs(worker/main.py:161)でも回収されない。config.py:13-15に実行時間の上限の設定は無い。CLIタブにはcore/cli_session.py:97の中断の仕組みがあるが、実装ジョブとアイデア出しジョブには無い。

## 関連ファイル

- worker/main.py:58
- worker/idea_runner.py:47
- worker/heartbeat.py:9
- core/config.py:13
## 実行指示（2026-11-24 10:21:06 UTC）

アイデアマンの提案を実装する。

## 提案タイトル

実装ジョブ・アイデア出しジョブに最大実行時間を設け、超えたら要確認にする

## 概要

Claude実行に上限時間が無く、Claudeが応答しなくなるとワーカーが手動で止めるまで占有されます。上限時間を設定項目に追加し、超えたら打ち切って要確認にします。

## 詳細

- config.pyに、実装ジョブ用とアイデア出し用の最大実行時間を追加する。
- worker/main.pyの_run_claude_for_jobとidea_runner._executeで、Claude実行をasyncio.wait_forで包む。
- 上限を超えたら、実装ジョブはneeds_attention、アイデア出しジョブはfailedにする。
- 打ち切った理由をイベントとエラーメッセージに残す。
- 上限超過時の状態遷移をテストで確認する。

## 根拠

worker/main.py:69とworker/idea_runner.py:47は、asyncio.runでClaudeの終了を上限なしに待っている。worker/heartbeat.py:16-18は実行中にハートビートを送り続けるため、recover_stale_jobs(worker/main.py:161)でも回収されない。config.py:13-15に実行時間の上限の設定は無い。CLIタブにはcore/cli_session.py:97の中断の仕組みがあるが、実装ジョブとアイデア出しジョブには無い。

## 関連ファイル

- worker/main.py:58
- worker/idea_runner.py:47
- worker/heartbeat.py:9
- core/config.py:13

