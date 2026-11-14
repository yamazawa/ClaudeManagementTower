# Claude管理塔

GitHub Issue連動型AI開発タスク管理システム。

詳細仕様は [`Input/Claude監視塔_設計書.html`](./Input/Claude監視塔_設計書.html) を参照する。\
実装計画は [`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md) を参照する。

## 現状

FastAPIサーバー、Git連携（サブタスク作成）、ワーカー基盤（単一ワーカー）まで実装済み（Phase 5）。\
Claude実行統合・並列実行・遠隔アクセスはこれから行う。

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
