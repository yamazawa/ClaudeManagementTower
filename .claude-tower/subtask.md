# サブタスク: [IdeaMan] リポジトリ切り替え時は前回のIssue一覧をすぐ表示し、画面を止めずに再取得するー①

アイデアマンの提案を実装する。

## 提案タイトル

リポジトリ切り替え時は前回のIssue一覧をすぐ表示し、画面を止めずに再取得する

## 概要

リポジトリを切り替えるたびに、GitHubからIssue一覧を取得し終わるまで画面がブロックされる。前回取得した一覧があればすぐ表示し、最新の一覧は画面を止めずに取り直して差し替える。

## 詳細

- 画面側で、リポジトリとフィルタの組ごとに最後に取得したIssue一覧を保持する。
- selectProjectでは、保持している一覧があればapplyIssueListですぐ描画する。その上でreloadIssues({ blocking: false })により最新の一覧に差し替える。
- 保持している一覧が無い初回だけ、従来どおり画面をブロックして「更新中…」を表示する。
- pollOpenIssues（60秒ごと）で取得したOpen一覧も、この保持データに入れて使い回す。
- 再取得の結果で選択中のIssueが消えた場合は、既存の再選択の処理にそのまま任せる。

## 根拠

- app.js:762-774 のselectProjectは、runSelectionRequestを画面ブロックありの既定値で呼んでいる。そのためIssue一覧（gh）と先頭Issueの詳細（gh）を順に取得し終わるまで操作できない。
- app.js:827-842 のpollOpenIssuesは、全リポジトリのOpen一覧を60秒ごとに取得している。しかし保存しているのはIssue番号だけ（openIssueNumbersByProject）で、一覧の表示には使っていない。
- 画面を止めない再取得の仕組み（runSelectionRequestのblocking:false、app.js:262-271）は既にあり、それを使い回せる。

## 関連ファイル

- app/static/app.js:262
- app/static/app.js:762
- app/static/app.js:827
- app/static/app.js:841
- app/static/app.js:1084
- app/static/app.js:1095
