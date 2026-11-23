# サブタスク: [IdeaMan] アイデアマン設計案をgitに登録するか、9章の参照先を見直すー①

アイデアマンの提案を実装する。

## 提案タイトル

アイデアマン設計案をgitに登録するか、9章の参照先を見直す

## 概要

IMPLEMENTATION_PLAN.md 9章が参照するInput/アイデアマン_設計案.htmlがgitに登録されていない。clone先では参照先が存在しない。

## 詳細

- 公開リポジトリのため、設計案に環境固有のパス・ホスト名・認証情報が含まれていないかを先に確認する。
- 問題がなければ、設計書（Claude監視塔_設計書.html）と同様にgitへ登録する。
- 登録しない場合は、9章の「設計案10章No.5」等の参照を、本文に必要な内容を書き写す形に改める。
- CLAUDE.mdの参照ドキュメントの優先順位に、アイデアマン設計案の位置づけ（未確定のv0.1）を追記するかを検討する。

## 根拠

git statusで、Input/アイデアマン_設計案.htmlだけがuntrackedになっている。
同じフォルダのClaude監視塔_設計書.htmlは登録済みである。
.gitignoreにInputやhtmlの除外指定はない。
IMPLEMENTATION_PLAN.md 253行目が設計案を参照しており、268〜269行目では設計案の章番号も引用している。
worktreeで作業するClaudeからは、この設計案を読めない。

## 関連ファイル

- IMPLEMENTATION_PLAN.md:253
- IMPLEMENTATION_PLAN.md:268
- Input/アイデアマン_設計案.html
## 実行指示（2026-11-23 12:44:05 UTC）

アイデアマンの提案を実装する。

## 提案タイトル

アイデアマン設計案をgitに登録するか、9章の参照先を見直す

## 概要

IMPLEMENTATION_PLAN.md 9章が参照するInput/アイデアマン_設計案.htmlがgitに登録されていない。clone先では参照先が存在しない。

## 詳細

- 公開リポジトリのため、設計案に環境固有のパス・ホスト名・認証情報が含まれていないかを先に確認する。
- 問題がなければ、設計書（Claude監視塔_設計書.html）と同様にgitへ登録する。
- 登録しない場合は、9章の「設計案10章No.5」等の参照を、本文に必要な内容を書き写す形に改める。
- CLAUDE.mdの参照ドキュメントの優先順位に、アイデアマン設計案の位置づけ（未確定のv0.1）を追記するかを検討する。

## 根拠

git statusで、Input/アイデアマン_設計案.htmlだけがuntrackedになっている。
同じフォルダのClaude監視塔_設計書.htmlは登録済みである。
.gitignoreにInputやhtmlの除外指定はない。
IMPLEMENTATION_PLAN.md 253行目が設計案を参照しており、268〜269行目では設計案の章番号も引用している。
worktreeで作業するClaudeからは、この設計案を読めない。

## 関連ファイル

- IMPLEMENTATION_PLAN.md:253
- IMPLEMENTATION_PLAN.md:268
- Input/アイデアマン_設計案.html

