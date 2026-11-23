# サブタスク: [IdeaMan] 起動時に、承認処理中のまま残った提案を復旧するー①

アイデアマンの提案を実装する。

## 提案タイトル

起動時に、承認処理中のまま残った提案を復旧する

## 概要

承認処理中にサーバーが止まると、提案がapproved_*のまま残り、画面から再操作できなくなる。起動時に承認前の状態へ戻す復旧処理を追加する。

## 詳細

- core/idea_approval.pyに、起動時の復旧処理を追加する。
- 処理内容は、状態がAPPROVED_ISSUE_ONLY・APPROVED_WITH_SUBTASKの提案を探し、release_claimと同じ規則で戻すこととする。
  - created_issue_numberがあればISSUE_CREATEDに戻す。
  - なければPROPOSEDに戻す。
- app/main.pyのlifespanで、recover_interrupted_sessionsの隣から呼び出す。
- Issue作成が成功し、番号の記録前に停止した場合はIssueが重複しうる。この残存リスクを9章に記録する。
- 9章「人間の確認が必要な事項」の、手動DB修正の記述を更新する。
- 状態ごとの復旧結果をテストで確認する。

## 根拠

core/idea_approval.py 51〜70行目のclaim_ideaは、承認開始時に状態をapproved_*に更新する。
承認前の状態に戻すのは、92〜104行目のrelease_claim（GitHub操作が失敗したとき）だけである。
app/main.py 21〜27行目のlifespanは、CLI対話の復旧（recover_interrupted_sessions）とマージの復旧は行っている。
しかし、提案の復旧は行っていない。
IMPLEMENTATION_PLAN.md 285行目に、「承認操作中にサーバーが停止した場合、提案が承認処理中のまま残る。現状は手動でのDB修正が必要」と記載がある。

## 関連ファイル

- core/idea_approval.py:51
- core/idea_approval.py:92
- core/ideas.py:29
- app/main.py:21
- core/cli_session.py:443
- IMPLEMENTATION_PLAN.md:285
