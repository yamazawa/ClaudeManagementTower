# サブタスク: [IdeaMan] 実装ジョブの状態表示を日本語・色分けにし、失敗理由を表示するー①

アイデアマンの提案を実装する。

## 提案タイトル

実装ジョブの状態表示を日本語・色分けにし、失敗理由を表示する

## 概要

MR内容ペインの実装ジョブの状態が「状態: failed」のように英語のまま、色分けなしで表示される。状態を日本語にして色分けし、失敗した場合はその理由を画面に出す。

## 詳細

・ジョブ状態（queued/running/succeeded/failed/needs_attention等）の表示文言を定数にまとめ、日本語で表示する。
・.job-statusに状態ごとのクラスを付け、実行中はスピナー、失敗・要確認は警告色、成功はアクセント色にする。
・GET /api/jobs/{id} と _latest_job_summary の返却値に error_message を追加する。
・失敗時は状態の下に error_message を表示し、長い文は末尾を省略してツールチップで全文を出す。

## 根拠

app.js:1812とapp.js:2258で job.status の値をそのまま「状態: ${job.status}」として出している。ガイドラインの「Enum定義は日本語にせず、表示はConverterで変換する」に合っていない。.job-status（style.css:954-957）には状態ごとの見た目の指定がない。ExecutionJobにはerror_message列がある（core/models.py:66）が、app/routes/jobs.py:20-30とapp/routes/projects.py:50の返却値に含まれず、MR内容ペインで失敗理由が見えない。アイデアマンのダイアログでは error_message をツールチップに出している（idea_dialog.js:166）ので、画面ごとに表示が揃っていない。最近の実行でも「JSON message exceeded maximum buffer size」「TLS handshake timeout」などの失敗が続いており、理由が画面で見えると原因を追いやすい。

## 関連ファイル

- app/static/app.js:1805
- app/static/app.js:2258
- app/static/style.css:954
- app/routes/jobs.py:20
- app/routes/projects.py:40
- core/models.py:66
- app/static/idea_dialog.js:166
## 実行指示（2026-11-23 06:44:20 UTC）

アイデアマンの提案を実装する。

## 提案タイトル

実装ジョブの状態表示を日本語・色分けにし、失敗理由を表示する

## 概要

MR内容ペインの実装ジョブの状態が「状態: failed」のように英語のまま、色分けなしで表示される。状態を日本語にして色分けし、失敗した場合はその理由を画面に出す。

## 詳細

・ジョブ状態（queued/running/succeeded/failed/needs_attention等）の表示文言を定数にまとめ、日本語で表示する。
・.job-statusに状態ごとのクラスを付け、実行中はスピナー、失敗・要確認は警告色、成功はアクセント色にする。
・GET /api/jobs/{id} と _latest_job_summary の返却値に error_message を追加する。
・失敗時は状態の下に error_message を表示し、長い文は末尾を省略してツールチップで全文を出す。

## 根拠

app.js:1812とapp.js:2258で job.status の値をそのまま「状態: ${job.status}」として出している。ガイドラインの「Enum定義は日本語にせず、表示はConverterで変換する」に合っていない。.job-status（style.css:954-957）には状態ごとの見た目の指定がない。ExecutionJobにはerror_message列がある（core/models.py:66）が、app/routes/jobs.py:20-30とapp/routes/projects.py:50の返却値に含まれず、MR内容ペインで失敗理由が見えない。アイデアマンのダイアログでは error_message をツールチップに出している（idea_dialog.js:166）ので、画面ごとに表示が揃っていない。最近の実行でも「JSON message exceeded maximum buffer size」「TLS handshake timeout」などの失敗が続いており、理由が画面で見えると原因を追いやすい。

## 関連ファイル

- app/static/app.js:1805
- app/static/app.js:2258
- app/static/style.css:954
- app/routes/jobs.py:20
- app/routes/projects.py:40
- core/models.py:66
- app/static/idea_dialog.js:166

