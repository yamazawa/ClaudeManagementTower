# サブタスク: [IdeaMan] style.cssに直接書かれた色を変数にまとめ、重複した指定を統合するー①

アイデアマンの提案を実装する。

## 提案タイトル

style.cssに直接書かれた色を変数にまとめ、重複した指定を統合する

## 概要

style.cssで、ヘッダーの背景色やトークン使用状況の警告色、お絵かきダイアログの赤などが:rootの変数を使わずに直接書かれている。同じ対象への指定が2か所に分かれている箇所もあるので、変数への集約と統合を行う。

## 詳細

・ヘッダー背景（#18243c）、トークン使用状況の文字色（#b8c7e3/#7a869e/#e38b39/#ff6b6b）、お絵かきツールの選択色（#e01e1e）、白背景（#fff）を:rootの変数にする。
・.issue-item/.subtask-rowの指定（891-902行と919-924行）を1つにまとめる。
・.mr-status-filter-segments .mr-status-filter-buttonの指定（589-593行と600-605行）を1つにまとめる。
・見た目が変わらないことを、変更前後のスクリーンショットで人間が確認する。

## 根拠

ガイドラインの「見た目の調整に使う値は、あとで変更しやすいよう1クラスに纏めて」に対して、style.css:40・637-652・1063などで色の値を直接書いている。style.css:891-902ではjustify-content: space-between・align-items: baselineを指定しているのに、style.css:919-924でflex-start・centerに上書きしている。後から読んだ人が、どちらが効いているのか判断しにくい。No.2の状態バッジのように色を増やす改善をする前に、色の値を1か所にまとめておくと変更しやすい。

## 関連ファイル

- app/static/style.css:1
- app/static/style.css:40
- app/static/style.css:637
- app/static/style.css:891
- app/static/style.css:919
- app/static/style.css:589
- app/static/style.css:600
- app/static/style.css:1063
