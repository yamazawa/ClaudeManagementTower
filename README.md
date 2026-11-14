# Claude管理塔

GitHub Issue連動型AI開発タスク管理システム。

詳細仕様は [`Input/Claude監視塔_設計書.html`](./Input/Claude監視塔_設計書.html) を参照する。\
実装計画は [`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md) を参照する。

## 現状

FastAPIサーバーの基盤（設定読み込み・SQLiteモデル・`gh`/Claude Agent SDKラッパー）まで実装済み（Phase 2）。\
Web画面・Git連携・ワーカーの実装はこれから行う。

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

起動後、`http://127.0.0.1:8000/docs` でAPIを確認できる。\
ワーカーの起動コマンドはPhase 5で確定する。
