# サブタスク: [IdeaMan] gitのfetch・push・pullに、一時的な通信エラー時の再試行を入れるー①

アイデアマンの提案を実装する。

## 提案タイトル

gitのfetch・push・pullに、一時的な通信エラー時の再試行を入れる

## 概要

ghには一時的な通信エラーの再試行がありますが、gitの通信処理にはありません。1回の通信エラーで実装ジョブやサブタスク作成が失敗します。

## 詳細

- github_client.pyと同じ形で、一時的な通信エラーの判定文字列と再試行の回数・間隔をgit_client.pyに追加する。
- 判定文字列の例は、Could not resolve host、Connection timed out、RPC failed、early EOFなど。
- 通信を伴う操作（fetch・push・pull・リモートブランチ削除）にだけ再試行を適用する。
- 判定処理をgithub_client.pyと共通化できるか検討する。
- 再試行のテストを追加する。

## 根拠

core/github_client.py:17-34,73-87では、TLS handshake timeoutなどを最大3回まで再試行している。core/git_client.py:19-33の_run_gitは1回失敗するとそのまま例外を投げる。対象はpush_branch(105)、create_worktreeのfetch(52)、prepare_detached_worktreeのfetch(194)、pull_latest(162)。worker/main.py:102はClaudeの実行前にpushするため、1回の通信エラーでジョブ全体がfailedになる。最近の失敗にもTLS handshake timeoutがある（#153⑤）。

## 関連ファイル

- core/git_client.py:19
- core/git_client.py:105
- core/git_client.py:52
- core/github_client.py:73
- worker/main.py:102
