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

`Input\アイデアマン_設計案.html`は、アイデアマン機能の未確定の設計案（v0.1）とする。\
確定事項として扱わず、実装で採用した方式はIMPLEMENTATION_PLAN.md 9章を優先する。

`CharpGuideLine.md`・`WpfGuideLine.md`は対象外とする。\
本プロジェクトはPython/FastAPIであり、C#/WPF向け知見は機械的に適用しない。

# 技術方針（確定済み）

- GitHub操作は`gh` CLIのサブプロセス実行。認証は`gh auth login`済みの既存OAuthセッションを使い回す。専用PATは発行しない。
- Claude実行は公式Claude Agent SDK（Python）を使う。CLIサブプロセス直接呼び出しは採用しない。
- GitHubホスティングはgithub.com（SaaS）。セルフホストは対象外。

# 実行・テスト時の注意点

ローカルでのFastAPI起動・pytest実行は隔離環境のため自由に行ってよい。

サブタスクのworktree内では、本体の仮想環境へのジャンクションが\
`./.venv`に作成されている（worktree作成時に自動設定）。\
`python`コマンドは使わず、`./.venv/Scripts/python.exe -m pytest -q`で\
テストを実行する。\
作業は対象worktree内で行うことを基本とする。\
ガイドライン更新等のため、`C:\git`配下の他リポジトリへの書き込みは許可されている。\
他のworktreeと管理塔自身のフォルダへの書き込みは拒否される。\
Read・Glob・Grepツールによるworktree外の参照は許可されている。\
秘密鍵・`.env`・認証情報ファイル等は、場所を問わず参照・書き込みが拒否される。\
ルールの詳細は`core/claude_access_rules.py`を参照する。

検証用リポジトリは使用しない（`yamazawa/claude-tower-test-repo`は2026-11-25に廃止）。\
自律実行機能の新規実装・未検証の変更も、本リポジトリで動作確認する。

本プロジェクト自身のリポジトリ（`yamazawa/ClaudeManagementTower`）への\
自律実行は、以下の安全対策が完了したため解禁する（2026-11-17判断）。

- Bash/PowerShellの操作範囲制限（worktree外への逃げ道・force push等の拒否）
- GitHub側のbranch protection（直接push・force pushの禁止、管理者にも適用）
- Issueの自動クローズ・PRの自動マージを行わない方針の実機確認

ただし以下は引き続き守る。
- PRのマージは人間が明示的に指示した場合のみ行う（自動マージはしない）。
- 最初は影響の小さいタスクから試し、Issue・PR・コミット内容を都度確認する。

本リポジトリ（`yamazawa/ClaudeManagementTower`）は公開（Public）。\
実IPアドレス、Cloudflareトンネルの固有ホスト名・トークン、認証情報、ローカル環境固有のユーザー名を含むパス等は、コミット・push・Issue・PR・コメントのいずれにも記載しない。

# 進行管理

開発はIMPLEMENTATION_PLAN.mdのPhase順に進める。\
Issue・MRの命名は管理塔の命名規則に従う（CommonGuideLine.md準拠）。\
Issue名は対応内容を表す日本語の文とし、スプリント番号・タスク番号は付けない。\
MR名は「Issue名ーMR固有名」とする（区切りは全角の「ー」）。
