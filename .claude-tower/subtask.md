# サブタスク: DevGuidelinesを管理塔に登録し、Issue・MRの命名を管理塔のルールに揃えるー①

管理塔側に残る`[SPn]タスクn - 内容`形式の記載を廃止する。
CommonGuideLine.mdでスプリント番号・タスク番号をIssue名に付けるルールを廃止したため、それに合わせる。

1. CLAUDE.md 63行目のIssueタイトル形式の記載を、管理塔の命名規則（Issue名は内容を表す日本語の文、MR名は「Issue名ーMR固有名」）に変更する。
2. IMPLEMENTATION_PLAN.md 2章（112行目）の`[SPn]`形式を使う記載を同様に変更する。
3. core/repo_initial_setup.py 35行目のSETUP_ISSUE_TITLEから`[SP0]タスク1 - `を外し「Claude監視塔の管理用初期設定」にする。
4. IMPLEMENTATION_PLAN.md 10章No.4（321行目）のIssue名も合わせて変更する。
5. 関連テストがあれば更新し、`./.venv/Scripts/python.exe -m pytest -q`で確認する。

コミットは上記の対応ごとに分ける。
