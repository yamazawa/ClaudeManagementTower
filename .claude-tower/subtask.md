# サブタスク: CLI機能の追加ー⑦

アイデアマンの提案を実装する。

## 提案タイトル

CLIタブで応答中のClaudeを中断できるようにする

## 概要

開発PCのEscキーのように、応答中のClaudeを止める「中断」ボタンをCLIタブに追加する。今は応答が終わるまで待つしかなく、間違った方向の作業を止められない。

## 詳細

- POST /api/cli-sessions/{id}/interrupt を追加する。
- run_turnのスレッドごとに中断用の目印（asyncio.Taskなど）を持ち、中断の要求を受けたらClaudeの実行を止める。
- 中断したら発言一覧に「利用者が中断しました」を残し、状態を発言待ち（idle）に戻す。
- claude_session_idは保存し、次の発言で会話を続けられるようにする。
- 画面は応答中だけ送信ボタンの横に中断ボタンを出す。文言はCLI_VIEW_MESSAGESにまとめる。
- テストでは、中断後にidleへ戻ることと、次の発言を受け付けることを確認する。

## 根拠

core/cli_session.py:195-222 はClaudeの実行をdaemonスレッドの中のasyncio.runで動かしているが、外から止める手段がない。app/routes/cli.py にも中断のAPIは無い。app/static/cli_view.js:165-175 は応答中に送信ボタンを無効にするだけで、中断の操作がない。なお、応答中を解除しているのはサーバー再起動時の recover_interrupted_sessions（core/cli_session.py:241-251）だけである。

## 関連ファイル

- core/cli_session.py:195
- core/cli_session.py:217
- app/routes/cli.py:51
- app/static/cli_view.js:46
- app/static/cli_view.js:165
## 実行指示（2026-11-23 10:51:35 UTC）

アイデアマンの提案を実装する。

## 提案タイトル

CLIタブで応答中のClaudeを中断できるようにする

## 概要

開発PCのEscキーのように、応答中のClaudeを止める「中断」ボタンをCLIタブに追加する。今は応答が終わるまで待つしかなく、間違った方向の作業を止められない。

## 詳細

- POST /api/cli-sessions/{id}/interrupt を追加する。
- run_turnのスレッドごとに中断用の目印（asyncio.Taskなど）を持ち、中断の要求を受けたらClaudeの実行を止める。
- 中断したら発言一覧に「利用者が中断しました」を残し、状態を発言待ち（idle）に戻す。
- claude_session_idは保存し、次の発言で会話を続けられるようにする。
- 画面は応答中だけ送信ボタンの横に中断ボタンを出す。文言はCLI_VIEW_MESSAGESにまとめる。
- テストでは、中断後にidleへ戻ることと、次の発言を受け付けることを確認する。

## 根拠

core/cli_session.py:195-222 はClaudeの実行をdaemonスレッドの中のasyncio.runで動かしているが、外から止める手段がない。app/routes/cli.py にも中断のAPIは無い。app/static/cli_view.js:165-175 は応答中に送信ボタンを無効にするだけで、中断の操作がない。なお、応答中を解除しているのはサーバー再起動時の recover_interrupted_sessions（core/cli_session.py:241-251）だけである。

## 関連ファイル

- core/cli_session.py:195
- core/cli_session.py:217
- app/routes/cli.py:51
- app/static/cli_view.js:46
- app/static/cli_view.js:165

