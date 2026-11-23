# サブタスク: [IdeaMan] Issue一覧の取得結果をサーバー側で短時間キャッシュするー①

アイデアマンの提案を実装する。

## 提案タイトル

Issue一覧の取得結果をサーバー側で短時間キャッシュする

## 概要

Issue一覧APIは呼ばれるたびにgh issue listを実行するため、リポジトリ切り替えやフィルタ変更のたびにGitHubとの通信を待つ。リポジトリと状態ごとに短時間キャッシュし、Issueを変更した時に破棄する。

## 詳細

- core/github_client.pyのlist_issues・list_issues_closed_sinceの結果を、(リポジトリ, 状態)をキーにしてメモリ上に保持する。保持時間はconfigで設定し、目安は30〜60秒とする。
- Issueの作成・Close・ReOpen・名前変更が成功したら、そのリポジトリのキャッシュを破棄する。
- 画面の60秒ごとの定期取得（pollOpenIssues）も同じキャッシュを使うようにする。
- 管理塔の外でIssueが変更された場合は、保持時間が過ぎるまで画面に反映されない。この遅れを許容するかを人間に確認する。
- キャッシュの有効期限と破棄の動きをpytestで確認する。

## 根拠

- app/routes/projects.py:75-88 のget_issuesは、毎回_list_issues_by_state経由でgh issue list（--limit 200）を実行している。
- core/github_client.py:66-80 では、一時エラー時に最大3回まで、待ち時間を伸ばしながら再試行するため、通信状況が悪いと1回の表示が長引く。
- app.js:762-774（リポジトリ選択）、1084-1090（フィルタ変更・Close/ReOpen後の再読込）、827-831（全リポジトリを60秒ごとに取得）が、すべてこのAPIを呼んでいる。
- MRステータスフィルタの選択中は、app.js:1170でopenとclosedの2回のgh呼び出しが発生する。
- 実行履歴に「TLS handshake timeout」での失敗があり、GitHubへの問い合わせ回数を減らすことは安定性にも効く。

## 関連ファイル

- app/routes/projects.py:75
- app/routes/projects.py:142
- app/routes/projects.py:252
- app/routes/projects.py:275
- core/github_client.py:83
- core/github_client.py:96
- app/static/app.js:827
- app/static/app.js:1157
