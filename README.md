# Claude管理塔

GitHub Issue連動型AI開発タスク管理システム。

詳細仕様は [`Input/Claude監視塔_設計書.html`](./Input/Claude監視塔_設計書.html) を参照する。\
実装計画は [`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md) を参照する。

## 現状

実装前の準備段階（Phase 0）。\
フォルダ構成・設定ファイル・CLAUDE.mdを配置した。\
FastAPIサーバー・ワーカーの実装はこれから行う。

## セットアップ（予定）

```
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
```

起動コマンドは実装（Phase 2以降）で確定する。
