# サブタスク: [IdeaMan] MRの状態を色付きバッジで表示するー①

アイデアマンの提案を実装する。

## 提案タイトル

MRの状態を色付きバッジで表示する

## 概要

MR一覧とMR見出しの状態（Draft/Resolving/Resolved/Merging/Merged/Deploying/Deployed/Canceled）がすべて同じ灰色の小さい文字で表示され、一覧を見ただけでは進み具合が分かりにくい。状態ごとに色を変えたバッジで表示する。

## 詳細

・renderSubtaskStateで、状態に応じたクラス（state-resolving等）を付ける。
・.subtask-stateを角の丸いバッジにし、状態ごとに背景色・文字色を割り当てる。
・Resolving・Merging・Deployingは処理中と分かるよう、点滅などの動きを付ける。
・マージ失敗を併記する場合は警告色にする。
・色の値はstyle.cssの:rootの変数にまとめる。

## 根拠

app.js:1443では、どの状態でも同じclass="subtask-state"のspanで出力している。style.css:940-952で、.subtask-stateはすべての状態でcolor: var(--muted)・font-size: 12pxの1種類だけになっている。命名規則に合わないMR名には警告色と⚠記号を付けている（style.css:932-938）のに、状態には見た目の区別がない。ヘッダーのMRステータスフィルタで状態ごとの件数を出している（style.css:599-612）ので、一覧側でも状態を色で見分けられると対応が分かりやすい。

## 関連ファイル

- app/static/app.js:1435
- app/static/app.js:32
- app/static/style.css:940
- app/static/style.css:932
## 実行指示（2026-11-23 06:42:45 UTC）

アイデアマンの提案を実装する。

## 提案タイトル

MRの状態を色付きバッジで表示する

## 概要

MR一覧とMR見出しの状態（Draft/Resolving/Resolved/Merging/Merged/Deploying/Deployed/Canceled）がすべて同じ灰色の小さい文字で表示され、一覧を見ただけでは進み具合が分かりにくい。状態ごとに色を変えたバッジで表示する。

## 詳細

・renderSubtaskStateで、状態に応じたクラス（state-resolving等）を付ける。
・.subtask-stateを角の丸いバッジにし、状態ごとに背景色・文字色を割り当てる。
・Resolving・Merging・Deployingは処理中と分かるよう、点滅などの動きを付ける。
・マージ失敗を併記する場合は警告色にする。
・色の値はstyle.cssの:rootの変数にまとめる。

## 根拠

app.js:1443では、どの状態でも同じclass="subtask-state"のspanで出力している。style.css:940-952で、.subtask-stateはすべての状態でcolor: var(--muted)・font-size: 12pxの1種類だけになっている。命名規則に合わないMR名には警告色と⚠記号を付けている（style.css:932-938）のに、状態には見た目の区別がない。ヘッダーのMRステータスフィルタで状態ごとの件数を出している（style.css:599-612）ので、一覧側でも状態を色で見分けられると対応が分かりやすい。

## 関連ファイル

- app/static/app.js:1435
- app/static/app.js:32
- app/static/style.css:940
- app/static/style.css:932

