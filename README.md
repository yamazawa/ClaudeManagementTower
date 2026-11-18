# Claude管理塔

GitHub Issue連動型AI開発タスク管理システム。

詳細仕様は [`Input/Claude監視塔_設計書.html`](./Input/Claude監視塔_設計書.html) を参照する。\
実装計画は [`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md) を参照する。

## 現状

Phase 10（統合受け入れテスト）まで完了し、受け入れチェックリスト全項目を実機確認済み。\
以下の安全対策の完了により、本リポジトリ自身の開発管理もアプリでの自律実行に移行した。

- Bash/PowerShellの操作範囲制限（worktree外への操作・force push・hard reset等を拒否）
- GitHub側のbranch protection（masterへの直接push・force pushを禁止、管理者にも適用）
- Issueの自動クローズ・PRの自動マージを行わない方針の実機確認

新規実装・未検証の変更は、引き続きテスト用リポジトリで検証してから本体に適用する。\
詳細は [`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md) の7章・8章を参照する。

## セットアップ

```
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
```

## 起動

サーバーとワーカーは常にセットで起動・再起動する運用のため、通常は以下の1コマンドでまとめて起動する。

```
python -u run_all.py
```

`Ctrl+C`で両方とも停止する。起動後、`http://127.0.0.1:8000/docs` でAPIを確認できる。

画面ヘッダーの以下のボタンで、サーバー・ワーカーを操作できる。\
サーバー再起動・ワーカー起動は`run_all.py`経由で起動した場合のみ使える。

- サーバー再起動：サーバーのみ再起動する。ワーカーと実行中のジョブには影響しない。
- ワーカー起動：ワーカーが停止している場合のみ起動する。

ワーカーは`WORKER_COUNT`個を常に維持する。\
終了したワーカーは`WORKER_RESPAWN_DELAY_SECONDS`経過後に自動で再起動する。\
ワーカーの起動・再起動時は、登録済みで稼働中のワーカー（取り残されたプロセスを含む）を停止してから起動する。
- ワーカー掃除：オフラインのワーカー行を削除し、停滞したジョブを要確認にする。
- マージして最新化：Claude管理塔リポジトリのDraftでないPRを全てマージし、本体を最新化してサーバー・ワーカーを再起動する。

マージして最新化では、競合しているPRにmasterを取り込み、Claudeが競合を解消してからマージする。\
競合解消用のworktreeは`WORKTREE_BASE_DIR`配下の`merge-pr-{PR番号}`に作成し、再実行時は再利用する。\
競合を解消できなかったPRはマージせず、画面に理由を表示して残りのPRの処理を続ける。

### 自動復旧（死活監視）

`run_all.py`の停止・再起動忘れに備え、タスクスケジューラで\
`scripts/watchdog.ps1`を5分おきに実行する運用にしている。\
`/health`への応答が無ければ`run_all.py`を自動起動する。\
`run_all.py`自身が多重起動防止のロックを持つため、\
既に起動中の場合に重ねて実行しても安全。

タスク登録例（現在のユーザー権限で、5分おきに実行）。

```
schtasks /create /tn "ClaudeTowerWatchdog" /sc minute /mo 5 /rl LIMITED /f /tr "powershell.exe -NoProfile -WindowStyle Hidden -File C:\git\ClaudeManagementTower\scripts\watchdog.ps1"
```

### 個別起動（デバッグ用途）

サーバー・ワーカーのどちらかだけを再起動したい場合は個別に起動できる。\
Windows既定の文字コード（cp932）では、Claude出力やGitHubの日本語データでUnicodeEncodeError・文字化けが発生するため、`PYTHONIOENCODING=utf-8`を必ず設定する。

```
$env:PYTHONIOENCODING = "utf-8"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

ワーカーは別プロセスで起動する。標準出力がバッファリングされ、ログがファイルに出力されるまで遅れることがあるため`-u`（無バッファ）を付ける。

```
$env:PYTHONIOENCODING = "utf-8"
python -u -m worker.main
```

複数ワーカー（`WORKER_COUNT`個）を起動する場合はランチャーを使う。単独起動はデバッグ用途。\
ランチャー・`run_all.py`の起動時は、個別起動したワーカーも停止対象になる。

```
$env:PYTHONIOENCODING = "utf-8"
python -u -m worker.launcher
```

## 遠隔アクセス（Cloudflare Tunnel + Access）

外出先から利用する場合、自宅PCのポートを直接公開せず、Cloudflare Tunnel経由で公開する。\
以下は一度だけ行う設定（`<ドメイン>`は取得済みの自分のドメインに置き換える）。

1. ドメインをCloudflareに追加する（Cloudflare Registrarで取得、またはネームサーバー変更で既存ドメインを追加）
2. `winget install --id Cloudflare.cloudflared` でインストールする
3. `cloudflared tunnel login` でブラウザ認証する
4. `cloudflared tunnel create claude-tower` でトンネルを作成する
5. `cloudflared tunnel route dns claude-tower claude-tower.<ドメイン>` でDNSを設定する
6. `%USERPROFILE%\.cloudflared\config.yml` を作成する

```yaml
tunnel: <tunnel create で表示されたID>
credentials-file: C:\Users\<ユーザー名>\.cloudflared\<tunnel ID>.json

ingress:
  - hostname: claude-tower.<ドメイン>
    service: http://127.0.0.1:8000
  - service: http_status:404
```

7. Cloudflare Zero Trustダッシュボード（https://one.dash.cloudflare.com）で、Access → Applications からSelf-hostedアプリケーションを作成する
   - Destination: `claude-tower.<ドメイン>`
   - Policy: Allow、Emailsで自分のメールアドレスのみ許可

設定後、サーバー起動中に以下でトンネルを起動する。

```
cloudflared tunnel run claude-tower
```

`https://claude-tower.<ドメイン>` にアクセスすると、Cloudflare Accessのログイン（ワンタイムコード等）を経てアプリに届く。\
アプリ側でのAccess JWT検証は実装していない。Access自体がオリジンへの到達を認証済みユーザーに限定するため、MVPではこれで十分と判断した。
