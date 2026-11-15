# Claude管理塔

GitHub Issue連動型AI開発タスク管理システム。

詳細仕様は [`Input/Claude監視塔_設計書.html`](./Input/Claude監視塔_設計書.html) を参照する。\
実装計画は [`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md) を参照する。

## 現状

Phase 9（遠隔アクセス）まで実装・実機確認済み。\
Phase 10（統合受け入れテスト）はこれから行う。

## セットアップ

```
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
```

## 起動

Windows既定の文字コード（cp932）では、Claude出力やGitHubの日本語データでUnicodeEncodeError・文字化けが発生する。\
`PYTHONIOENCODING=utf-8`を必ず設定して起動する。

```
$env:PYTHONIOENCODING = "utf-8"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

起動後、`http://127.0.0.1:8000/docs` でAPIを確認できる。

ワーカーは別プロセスで起動する。標準出力がバッファリングされ、ログがファイルに出力されるまで遅れることがあるため`-u`（無バッファ）を付ける。

```
$env:PYTHONIOENCODING = "utf-8"
python -u -m worker.main
```

複数ワーカー（`WORKER_COUNT`個）を起動する場合はランチャーを使う。単独起動はデバッグ用途。

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
