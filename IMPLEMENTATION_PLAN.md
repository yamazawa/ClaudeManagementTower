# Claude管理塔 実装計画

参照元設計書：`C:\git\ClaudeManagementTower\Input\Claude監視塔_設計書.html`\
参照ガイドライン：`C:\git\DevGuidelines\CommonGuideLine.md`

本ドキュメントは実装前の整理用であり、実装そのものはまだ開始しない。

# 1. 確定仕様の整理（設計書より）

## 1.1 業務ルール
- 1タスク = 1 GitHub Issue。
- 1サブタスク = 1 PR。専用ブランチを持つ。
- サブタスク完了は対応PRがマージされた時点。
- Issue完了は必要なサブタスクのPRが全てマージされた後。
- マージ前のレビューNGは同一ブランチ・同一PRで修正する。
- マージ後に発覚した問題のみ新規サブタスク・新規PRを作成する。
- PRの説明文は `Related to #番号`。`Closes #番号` は使わない。
- Claudeは原則質問せず、調査と合理的判断で実装を進める。
- 判断内容・理由・残る不確実性はHTMLレポートに記録する。
- Issueの開発進捗、PRのレビュー状態、Claudeワーカーの実行状態は別の値として管理・表示する。

## 1.2 システム構成
- Webサーバー（FastAPI）とClaude実行ワーカーをプロセス分離する。
- DBはSQLite、アクセスはSQLAlchemy ORM。
- 画面更新は3秒間隔ポーリング。WebSocketはMVPで不採用。
- Git操作はGit CLI、GitHub操作は`gh` CLI（サブプロセス実行）を使う。
- GitHub認証は`gh auth login`済みの既存OAuthセッションを使い回す。ワーカー専用PATは発行しない。このトークンはscope `repo`（アクセス可能な全リポジトリ）を持つため、対象リポジトリ限定の最小権限はアプリ側の許可リスト判定に委ねる。
- Windows上で稼働し、PowerShellとWindowsパスを前提にする。
- GitHubホスティングはgithub.com（SaaS）で確定。セルフホストは対象外。
- ワーカー数Nは設定可能、初期値3。
- 1ワーカーは同時に1ジョブのみ実行する。
- 同一サブタスクの並列実行は禁止する。
- サブタスクごとに専用Git worktreeを割り当てる。worktreeは`WORKTREE_BASE_DIR`配下、ブランチ名と同名のフォルダに作成する（Phase 4実装済み）。
- ブランチ作成後、サブタスクのタイトル・指示内容を`.claude-tower/subtask.md`に書き出す初期コミットを1件追加してからDraft PRを作成する（差分ゼロではDraft PR作成不可のため。Phase 1実機検証済み、ダミーコミットではなく意味のある内容とする）。
- Webサーバーはリクエスト処理中にClaude Codeを直接起動して待機しない。
- Claude実行は公式Claude Agent SDK（Python）を使う。内部的にはCLIサブプロセス方式と同じCLIバイナリ・同じエージェントループを使うが、`can_use_tool`コールバックでworktree外操作を確実に拒否できる点を優先してSDKを採用する。
- `can_use_tool`コールバックは`PermissionResultAllow`/`PermissionResultDeny`を返す（dictを返すとSDK側でエラーになる。Phase 1実機検証済み）。
- Webサーバー・ワーカープロセスは環境変数`PYTHONIOENCODING=utf-8`を設定して起動する（Windows既定のcp932では、Claude出力やGitHubの日本語データを標準出力に表示する際に文字化け・UnicodeEncodeErrorが発生するため。Phase 1・2で実機確認済み）。
- ワーカープロセスは`-u`（無バッファ出力）付きで起動する（標準出力をファイルにリダイレクトするとバッファリングされ、ログの反映が遅れるため。Phase 5実機確認済み）。

## 1.3 データ・排他制御
- ジョブ取得はSQLiteの短い書き込みトランザクションで原子的に行う。
- SQLiteはWALモード、busy_timeoutを設定する。
- ジョブ実行中はDBトランザクションを保持しない。
- 複数回の追加指示は`execution_jobs`を追加して履歴を消さない。
- SQLiteファイル・レポート・worktreeはGit管理対象から除外する。

## 1.4 HTMLレポート
- レポートは`sandbox=""`付きiframeで表示する。
- `allow-scripts`・`allow-same-origin`等は付与しない。
- 親画面のDOMへレポートHTMLを直接挿入しない。
- レポート応答には制限的なCSPを設定する。
- GitHub・Cloudflare・Claudeの認証情報をレポートやログに書き込まない。

## 1.5 セキュリティ・運用
- 外部アクセスはCloudflare Tunnel + Cloudflare Access経由とする。
- 自宅ルーターのポート開放は前提にしない。
- GitHub認証は`gh` CLIの既存OAuthセッション（Windows資格情報）を使い回す。Claude認証情報は環境変数等で保持する。いずれもブラウザへ送らない。
- 対象リポジトリ・worktreeは許可リストで制限する。
- 任意のOSコマンドをWebから直接実行させない。
- ワーカー異常終了時は該当ジョブを「要確認」にし、自動二重実行しない。
- 本プロジェクトのGitHubリポジトリは公開（Public）。自宅PCへの侵入につながる情報（実IPアドレス、Cloudflareトンネルの固有ホスト名・トークン、認証情報、ローカル環境固有のユーザー名を含むパス等）はコミット・push・Issue・PR・コメントに記載しない。

## 1.6 実装提案（初期実装として採用）
- API一覧（`/api/projects`等）は設計書記載の案を初期実装とする。
- PR/Issue状態同期はポーリング＋画面の「同期」操作とする。Webhookは不採用。
- フォルダ構成は設計書14.3の構成案を採用する。

# 2. 共通ガイドラインの適用（CommonGuideLine.md）

- Issue・PR・コミットコメントのフォーマット、文またぎ禁止等のドキュメントルールは本プロジェクトにも適用する。
- 本プロジェクトの開発用Issueタイトルはガイドラインの `[SPn]タスクn - 内容` 形式を使う。
- 管理塔が管理対象として扱うGitHub Issue自体の命名規則は制約しない。
- `CharpGuideLine.md`・`WpfGuideLine.md`は本プロジェクト（Python/FastAPI）には適用しない。
- プロジェクト固有の`CLAUDE.md`を作成し、参照優先順位と実行・テスト時の注意点を明記する。

# 3. ガイドラインと設計書の衝突点・採用方針

| No. | 項目 | ガイドライン内容 | 設計書内容 | 採用方針 |
|---|---|---|---|---|
| 1 | 実行時の制約 | 既存の作業・データに影響する可能性がある場合は人間に確認する | 環境検証でGitHubへの実ブランチ・Draft PR作成を実機確認する | 検証・開発には本番運用中のリポジトリを使わず、人間が指定するテスト用リポジトリのみを対象とする。対象リポジトリは事前に人間へ確認する |
| 2 | 破壊的git操作 | コマンド種別単位で事前許可済み、確認なしで実行する | force push・hard reset・強制削除等は自律実行しない | Claude管理塔ワーカーの実行コンテキストでは設計書を優先し、これらの操作をコード上でも許可しない |
| 3 | モデル構造変更時の互換性 | 移行コードを書かず、動作確認用データも合わせて更新する | DBスキーマ変更時は既存継続データの削除を事前確認する | 開発中（本番データなし）はガイデライン通り互換性コードなしで進める。運用開始後のスキーマ変更は設計書の事前確認ルールを優先する |

安全上重大な衝突（No.1）は実装前に人間へ確認する。

# 4. 実装工程の分割

| Phase | 内容 | 完了条件 | テスト方法 |
|---|---|---|---|
| 0 | プロジェクト初期化・CLAUDE.md作成・設定値の確定 | git init、フォルダ構成作成、CLAUDE.md配置、対象リポジトリ（owner/repo）が設定ファイルで外出しされている | ファイル配置の目視確認 |
| 1 | 環境検証 | `gh`経由でのIssue取得成功、差分ゼロブランチでのDraft PR作成可否が判明 | テスト用リポジトリ（claude-tower-test-repo）に対してスクリプトで実行し結果を記録 |
| 2 | 基盤構築 | FastAPI起動、SQLiteモデル作成・マイグレーション、設定読み込み、`gh` CLIラッパーと`claude-agent-sdk`の疎通 | `/docs`からの手動呼び出し、簡易スクリプトでのDB読み書き確認 |
| 3 | タスク画面（読み取り専用） | Issue一覧・詳細・サブタスク履歴が画面表示される | ブラウザでの目視確認 |
| 4 | Git連携 | サブタスク作成でブランチ・Draft PRが作成され、Issueへのリンクが`Related to #番号`になる | テスト用リポジトリで1件作成し、GitHub上で確認 |
| 5 | ワーカー基盤（単一ワーカー） | 別プロセスのワーカーがSQLiteジョブキューから原子的にジョブを取得できる | ジョブ投入→取得→状態更新の一連の動作をログで確認 |
| 6 | Claude実行統合 | ワーカーがClaude Agent SDKで対象worktree内のClaudeを実行し、`can_use_tool`によるworktree外操作の拒否とイベント保存が動作する | 簡単な指示で1件実行し、`execution_events`の内容と権限拒否の動作を確認 |
| 7 | 成果物処理 | コミット・push、HTMLレポート生成・sandbox iframe表示、Draft解除、PR状態同期が動作する | 実行後にGitHub上のPR状態とレポート表示を確認 |
| 8 | 並列実行化 | N=3でワーカーを起動し、異なる3件が並列実行、4件目は待機して順次開始する | 設計書16.4の受け入れ条件に沿って動作確認 |
| 9 | 遠隔アクセス | Cloudflare Tunnel + Access経由でスマホから表示・指示できる | スマホ実機での画面確認・指示送信確認 |
| 10 | 統合受け入れテスト | 設計書12章の受け入れチェックリスト全項目を満たす | チェックリストを1項目ずつ実機確認 |

各Phaseの着手前に、前Phaseの完了条件を満たしているか確認する。

# 5. 実装前に検証が必要な技術的課題

| No. | 課題 | 検証方法 | 状況 |
|---|---|---|---|
| 1 | 差分ゼロのDraft PR作成可否 | テスト用リポジトリで実機検証する | 検証済み。5.1参照 |
| 2 | `claude-agent-sdk`（Python）の呼び出し方法・`can_use_tool`コールバックによるworktree外操作の拒否・`resume`によるセッション継続 | テスト用リポジトリに対応するworktreeで実際に実行して検証する | 検証済み。5.1参照。Phase 6でワーカー本体への組み込みと`permission_denials`の記録も実機確認済み |
| 3 | `gh` CLIコマンド（`pr create --draft`・`pr ready`等）の具体的な呼び出し・エラーハンドリング | テスト用リポジトリで実際にサブプロセス実行して検証する | 検証済み。5.1参照 |
| 4 | SQLiteでの原子的ジョブ取得の実装パターン | WALモード・busy_timeout設定下でのトランザクション更新を検証する | 検証済み。`UPDATE ... RETURNING`で原子的に取得し、同一サブタスクはNOT EXISTS句で除外する（Phase 5実装・自動テスト済み） |
| 7 | サブタスク作成中（worktree作成〜Draft PR作成〜DB保存）の途中失敗時の復旧 | - | MVPでは未対応。失敗時はエラーを返すのみで、再試行・ロールバックは行わない。残存したworktree・ブランチの後始末は人間が行う（設計書7章で想定済みのリスク） |
| 5 | Windows環境でのGit worktree運用（パス長・権限） | テスト用リポジトリで複数worktree作成・削除を検証する | 検証済み。5.1参照 |
| 6 | Cloudflare Tunnel + AccessのJWT検証実装 | 後工程（Phase 9）で実機検証する | 未検証。Phase 9で実施 |

## 5.1 Phase 1 検証結果（2026-11-14、claude-tower-test-repoで実施）

| No. | 検証項目 | 結果 |
|---|---|---|
| 1 | `gh issue list/view --json`でのIssue取得 | 成功 |
| 2 | 差分ゼロのDraft PR作成 | 失敗（GitHubも不可）。`.claude-tower/subtask.md`への初期コミットで解決 |
| 3 | `gh pr ready`によるDraft解除 | 成功 |
| 4 | Git worktreeの作成・削除（Windows） | 成功。パス長・権限の問題は発生しなかった |
| 5 | Python環境 | 未導入だったため、Python 3.12.10をwingetで導入した |
| 6 | `claude-agent-sdk`の`query()`呼び出し | 成功。`SystemMessage`・`ResultMessage`等の型付きオブジェクトを取得できた |
| 7 | `resume`によるセッション継続 | 成功。同一session_idで2回目の実行がエラーなく継続した |
| 8 | `can_use_tool`によるworktree外操作の拒否 | dictを返すとSDK側でエラーになり、結果的に書き込みは防げたが正しい実装ではなかった。`PermissionResultAllow`/`PermissionResultDeny`を返す実装に修正が必要（1.2節に反映済み） |
| 9 | Windows標準出力のエンコーディング | 既定のcp932では、Claude出力に限らずGitHubの日本語データ表示でも文字化け・UnicodeEncodeErrorが発生した。`PYTHONIOENCODING=utf-8`をプロセス起動時に設定して解決（Phase 2で再確認、1.2節に反映済み） |

# 6. 実装開始前にユーザーへ確認が必要な情報

| No. | ファイル | 行 | 指摘内容 | 対応 |
|---|---|---|---|---|
| 1 | **C:\git\ClaudeManagementTower\Input\Claude監視塔_設計書.html** | 66 | Cloudflareドメイン・Access設定が未確定 | Phase 9着手時に人間へ確認する（MVP初期は未着手でよい） |
