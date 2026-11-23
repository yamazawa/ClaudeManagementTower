# サブタスク: [IdeaMan] app.jsを機能単位のファイルに分割するー①

アイデアマンの提案を実装する。

## 提案タイトル

app.jsを機能単位のファイルに分割する

## 概要

app.jsに、リポジトリ・デプロイ・Issue・MR・添付・ジョブ実行の処理が混在し、2400行を超えている。cli_view.jsやidea_view.jsと同じく、機能単位のファイルに分ける。

## 詳細

- 関数群を機能単位で分け、app/static配下に別ファイルとして切り出す。
- 分け方の案は、デプロイ（openDeployDialog〜waitForDeployResult）、Issue一覧（reloadIssues〜updateIssueItemCounts）、MR一覧・詳細（renderSubtaskList〜renderSubtaskActions）、添付（setupAttachmentForm〜uploadAttachment）、ジョブ実行（executeSubtask〜showReport）、MR状態フィルタ・レート制限（setupMrStatusFilter〜formatResetTime）とする。
- 共通処理（escapeHtml・postJson・runBusyAction等）は共通ファイルに集める。
- index.htmlのscriptタグを依存順に並べ直す。
- 動作は変えず、移動のみのコミットと整理のコミットを分ける。

## 根拠

app/static/app.jsに関数定義が176個あり、末尾のshowReportは2456行目にある。
同じファイルに、デプロイ（990〜1098行目）、Issue一覧（1100〜1279行目）、添付（1806〜1929行目）、ジョブ実行（2388〜2456行目）が並んでいる。
CLI・Ideaは、既にcli_view.js・idea_view.jsとして分かれている（index.html 179〜180行目）。
#153の実行が、JSONのバッファ上限（1MB）超過で繰り返し失敗している。
大きなファイルの読み込みも、上限超過の一因になっている可能性がある。

## 関連ファイル

- app/static/app.js:990
- app/static/app.js:1100
- app/static/app.js:1806
- app/static/app.js:2388
- app/static/index.html:177
