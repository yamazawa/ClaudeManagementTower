# サブタスク: [IdeaMan] サブタスク作成が途中で失敗したとき、作成済みのworktree・ブランチを後始末するー①

アイデアマンの提案を実装する。

## 提案タイトル

サブタスク作成が途中で失敗したとき、作成済みのworktree・ブランチを後始末する

## 概要

サブタスク作成は、worktree作成・コミット・push・Draft PR作成を順に行う。途中で失敗するとエラーを返すだけで、作成済みのものが残り、人間が手で消す必要がある。

## 詳細

- _push_draft_prで、どの段階まで成功したかを記録しながら実行する。
- 失敗時は、成功した段階を逆順に取り消す。
  - Draft PR作成前の失敗では、push済みのリモートブランチを削除する。
  - そのうえで、worktreeとローカルブランチを削除する。
- 後始末自体が失敗した場合は、残ったもの（ブランチ名・パス）をエラーメッセージに含めて返す。
- 後始末はforce系の操作を使わない範囲で行い、3章No.2の方針と矛盾しないことを確認する。
- Draft PR作成後のDB保存失敗は取り消さず、自動同期で管理塔外PRとして取り込まれる現状の動作を、5章No.7に記録する。
- 5章No.7の状況を更新する。

## 根拠

app/routes/subtasks.py 100〜112行目の_push_draft_prは、create_worktree・commit_subtask_instruction・push_branch・create_draft_prを順に呼ぶ。
156〜157行目は、例外をHTTP 500に変換するだけで後始末をしない。
IMPLEMENTATION_PLAN.md 148行目の5章No.7は、「MVPでは未対応。残存したworktree・ブランチの後始末は人間が行う」のままである。
最近の実行でも、#153⑤がTLSハンドシェイクのタイムアウトで失敗するなど、GitHub側の一時的な失敗が起きている。

## 関連ファイル

- app/routes/subtasks.py:100
- app/routes/subtasks.py:156
- core/git_client.py:38
- core/github_client.py:200
- IMPLEMENTATION_PLAN.md:148
