# サブタスク: [SPn]タスクn - gh CLIの一時的な通信エラーを再試行するー①

アイデアマンの提案を実装する。

## 提案タイトル

[SPn]タスクn - gh CLIの一時的な通信エラーを再試行する

## 概要

TLS handshake timeoutなどの一時的な通信エラーで、ジョブ全体がfailedになっています。安全な操作に限って、gh呼び出しを再試行します。

## 詳細

_run_ghで、stderrが一時的なエラー（TLS handshake timeout、connection reset、HTTP 502/503など）の場合は、間隔を空けて数回再試行します。
再試行の回数と間隔は定数にまとめます。
issue create・pr createのように、同じ操作を2回行うと二重に作成される操作は再試行の対象から外すか、作成済みかを確認してから再試行します。
Claude実行後の後処理（mark_pr_ready）が失敗した場合は、ジョブをfailedではなくneeds_attentionにすることも検討します。

## 根拠

#153 Issue、MRレイアウト改善ー⑤が「Post https://api.github.com/graphql: net/http: TLS handshake timeout」で失敗しています。
core/github_client.py:16-29の_run_ghには再試行がなく、エラーをそのまま例外にしています。
worker/main.py:85のmark_pr_ready（graphqlを使う）はClaude実行後に呼ばれるため、ここで失敗するとジョブ全体がfailedになります（worker/main.py:123-125）。

## 関連ファイル

- core/github_client.py:16
- worker/main.py:85
- worker/main.py:96
- worker/main.py:123
