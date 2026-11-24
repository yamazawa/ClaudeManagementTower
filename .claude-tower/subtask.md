# サブタスク: [IdeaMan] APIのエラーメッセージを日本語にそろえ、1か所に集約するー①

アイデアマンの提案を実装する。

## 提案タイトル

APIのエラーメッセージを日本語にそろえ、1か所に集約する

## 概要

HTTPExceptionのメッセージで英語と日本語が混在しています。画面に表示される文言を日本語にそろえ、1か所にまとめます。

## 詳細

- app/routes配下のエラーメッセージを、1つのモジュールに定数としてまとめる。
- 英語のメッセージ（project not foundやtitle is emptyなど）を日本語にする。
- 提案3の共通404関数と同じ定数を使う。
- メッセージの文字列を直接比較しているテストがあれば合わせる。

## 根拠

app/routes配下には英語のメッセージが20件、日本語のメッセージが8件ある。subtasks.py:228と338は英語、277と429は日本語で、同じファイルの中でも混在している。CommonGuideLineの「画面に表示する文言はリソースファイルに集約する」に沿っていない。

## 関連ファイル

- app/routes/subtasks.py:228
- app/routes/subtasks.py:277
- app/routes/projects.py:150
- app/routes/cli.py:68
- app/routes/jobs.py:19
