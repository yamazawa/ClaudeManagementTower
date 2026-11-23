# サブタスク: CLI機能の追加ー⑤

アイデアマンの提案を実装する。

## 提案タイトル

CLIタブのClaudeの応答文をMarkdownとして表示する

## 概要

Claudeの応答文は見出し・箇条書き・表・コードブロックを含むMarkdownだが、CLIタブではそのままのテキストで表示している。開発PCの画面と同じように読めるよう、Markdownを描画する。

## 詳細

- assistantの発言だけをMarkdownとして描画する。user・tool・errorは今のままテキストで表示する。
- 外部CDNは使わない。必要な範囲の小さな描画処理を自前で書くか、ライブラリをstaticに同梱する。
- 描画したHTMLは、許可したタグ以外を取り除いてから表示する（XSS対策）。
- コードブロックは等幅の枠に入れ、横スクロールできるようにする。
- 表・コードブロックの色や余白は、style.cssの:root変数にまとめる。

## 根拠

app/static/cli_view.js:148-157 の appendCliMessage は、message.contentをtextContentで入れている。app/static/style.css:350-354 はwhite-space: pre-wrapで改行を保つだけなので、表や見出しが記号のまま表示される。app配下にMarkdownを描画する処理は無い（「markdown」で検索しても見つからない）。管理塔からの依頼文は表形式の報告を求めているため、表が崩れて読みづらい。

## 関連ファイル

- app/static/cli_view.js:148
- app/static/style.css:350
- app/static/style.css:364
