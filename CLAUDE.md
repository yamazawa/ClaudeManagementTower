# Claude管理塔 プロジェクト指示

GitHub Issue連動型AI開発タスク管理システム。\
詳細仕様は `Input\Claude監視塔_設計書.html` を参照する。\
実装計画は `IMPLEMENTATION_PLAN.md` を参照する。

# 参照ドキュメントの優先順位

1. `Input\Claude監視塔_設計書.html`（確定事項）
2. `IMPLEMENTATION_PLAN.md`（設計書の確定事項とガイドラインの衝突点・採用方針）
3. `C:\git\DevGuidelines\CommonGuideLine.md`（全プロジェクト共通ルール）

設計書とCommonGuideLine.mdが衝突する場合、IMPLEMENTATION_PLAN.md 3章の記録を優先する。\
新たな衝突に気づいた場合、黙って解決せずIMPLEMENTATION_PLAN.mdに追記する。

`CharpGuideLine.md`・`WpfGuideLine.md`は対象外とする。\
本プロジェクトはPython/FastAPIであり、C#/WPF向け知見は機械的に適用しない。

# 技術方針（確定済み）

- GitHub操作は`gh` CLIのサブプロセス実行。認証は`gh auth login`済みの既存OAuthセッションを使い回す。専用PATは発行しない。
- Claude実行は公式Claude Agent SDK（Python）を使う。CLIサブプロセス直接呼び出しは採用しない。
- GitHubホスティングはgithub.com（SaaS）。セルフホストは対象外。

# 実行・テスト時の注意点

ローカルでのFastAPI起動・pytest実行は隔離環境のため自由に行ってよい。

GitHub操作の実機確認は `yamazawa/claude-tower-test-repo` のみを対象にする。\
他の実運用リポジトリ（本プロジェクト自身のリポジトリを含む）には絶対に操作しない。

本リポジトリ（`yamazawa/ClaudeManagementTower`）は公開（Public）。\
実IPアドレス、Cloudflareトンネルの固有ホスト名・トークン、認証情報、ローカル環境固有のユーザー名を含むパス等は、コミット・push・Issue・PR・コメントのいずれにも記載しない。

# 進行管理

開発はIMPLEMENTATION_PLAN.mdのPhase順に進める。\
Issueタイトルは `[SPn]タスクn - 内容` 形式（CommonGuideLine.md準拠）。
