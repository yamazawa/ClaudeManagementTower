# サブタスク: [IdeaMan] Issue選択時のGitHub問い合わせを省き、DB上のMR一覧のみで表示するー①

アイデアマンの提案を実装する。

## 提案タイトル

Issue選択時のGitHub問い合わせを省き、DB上のMR一覧のみで表示する

## 概要

Issueを選択するたびにgh issue viewを実行しているが、画面はIssue本文を使っていない。Issue一覧で取得済みの値とDB上のMR一覧で表示し、選択時の待ち時間をなくす。

## 詳細

- Issue選択時は、Issue一覧で取得済みのnumber・title・state・urlと、既存のDB専用API（/issues/{number}/subtasks）でIssue内容を組み立てる。
- 対象はselectIssue、fetchIssueSelection、refreshIssueDetail（ジョブ完了時）、openCreatedIssueAndSubtaskとする。
- Issue一覧に無い番号（fetchUnlistedIssue）は、従来どおり詳細APIで取得する。
- 詳細API（get_issue_detail）は残すが、画面の通常操作では呼ばないようにする。
- 効果は、Issue切り替え時に出る「更新中…」の時間の短縮を、手動で計測して確認する。

## 根拠

- app/routes/projects.py:243-249 のget_issue_detailは、毎回get_issue（gh issue view）を実行している。
- core/github_client.py:114-118 のget_issueはbodyを取得しているが、app.jsでIssueの.bodyを参照している箇所は無い（grepで確認）。
- 画面で使っているtitle・state・urlは、Issue一覧API（gh issue list --json number,title,state,url）の結果にすでにある。
- app.js:1506-1515 のselectIssueは、詳細取得が終わるまで画面をブロックして「更新中…」を表示する。
- app.js:2350 ではジョブ完了のたびにrefreshIssueDetailでgh問い合わせが発生している。
- MR一覧は、GitHubに問い合わせないAPI（projects.py:286-291）が既にある。

## 関連ファイル

- app/routes/projects.py:243
- core/github_client.py:114
- app/static/app.js:1124
- app/static/app.js:1506
- app/static/app.js:1549
- app/static/app.js:1558
- app/static/app.js:2175
- app/static/app.js:2350
## 実行指示（2026-11-23 07:17:53 UTC）

アイデアマンの提案を実装する。

## 提案タイトル

Issue選択時のGitHub問い合わせを省き、DB上のMR一覧のみで表示する

## 概要

Issueを選択するたびにgh issue viewを実行しているが、画面はIssue本文を使っていない。Issue一覧で取得済みの値とDB上のMR一覧で表示し、選択時の待ち時間をなくす。

## 詳細

- Issue選択時は、Issue一覧で取得済みのnumber・title・state・urlと、既存のDB専用API（/issues/{number}/subtasks）でIssue内容を組み立てる。
- 対象はselectIssue、fetchIssueSelection、refreshIssueDetail（ジョブ完了時）、openCreatedIssueAndSubtaskとする。
- Issue一覧に無い番号（fetchUnlistedIssue）は、従来どおり詳細APIで取得する。
- 詳細API（get_issue_detail）は残すが、画面の通常操作では呼ばないようにする。
- 効果は、Issue切り替え時に出る「更新中…」の時間の短縮を、手動で計測して確認する。

## 根拠

- app/routes/projects.py:243-249 のget_issue_detailは、毎回get_issue（gh issue view）を実行している。
- core/github_client.py:114-118 のget_issueはbodyを取得しているが、app.jsでIssueの.bodyを参照している箇所は無い（grepで確認）。
- 画面で使っているtitle・state・urlは、Issue一覧API（gh issue list --json number,title,state,url）の結果にすでにある。
- app.js:1506-1515 のselectIssueは、詳細取得が終わるまで画面をブロックして「更新中…」を表示する。
- app.js:2350 ではジョブ完了のたびにrefreshIssueDetailでgh問い合わせが発生している。
- MR一覧は、GitHubに問い合わせないAPI（projects.py:286-291）が既にある。

## 関連ファイル

- app/routes/projects.py:243
- core/github_client.py:114
- app/static/app.js:1124
- app/static/app.js:1506
- app/static/app.js:1549
- app/static/app.js:1558
- app/static/app.js:2175
- app/static/app.js:2350

