# サブタスク: CLI機能の追加ー④

アイデアマンの提案を実装する。

## 提案タイトル

CLIタブの指示に画像・ファイルを添付できるようにする

## 概要

開発PCでは画面のスクリーンショットを貼って指示できるが、CLIタブは文字だけしか送れない。MRの指示ですでに使っている添付の仕組みを使い、CLIの発言にも添付できるようにする。

## 詳細

- CLIの項目ごとに添付を置く場所を決める（リポジトリの外に、項目IDごとのフォルダを作る）。
- 送信APIで添付を受け取れるようにし、core/attachments.py の build_instruction_prompt と同じ形でパスを指示文に入れる。
- 画面は入力欄に添付ボタンを付け、クリップボードの画像の貼り付けにも対応する。
- 発言一覧には、添付したファイル名を利用者の発言と一緒に表示する。
- 添付を置く場所は、参照ルールでReadが許可される場所かを確認する。

## 根拠

app/routes/cli.py:30-31 の SendCliMessageRequest は text しか持たない。core/attachments.py:95・127 にはMR用の保存処理と指示文の組み立てがあり、core/claude_client.py:22-27 も添付画像を読み込めるようにバッファの上限を広げてある。それでもCLIの経路ではどちらも使っていない。画面の不具合を相談する時は、スクリーンショットがあると説明しやすい。

## 関連ファイル

- app/routes/cli.py:30
- core/cli_session.py:148
- core/attachments.py:95
- core/attachments.py:127
- core/claude_client.py:22
- app/static/cli_view.js:47
