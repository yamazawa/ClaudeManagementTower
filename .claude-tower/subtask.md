# サブタスク: [IdeaMan] 削除済みプロジェクトを参照したときのAttributeErrorをなくし、404判定をルート間で共通化するー①

アイデアマンの提案を実装する。

## 提案タイトル

削除済みプロジェクトを参照したときのAttributeErrorをなくし、404判定をルート間で共通化する

## 概要

プロジェクトの取得結果を確認せずに属性を参照している箇所が3つあります。承認処理では、承認中の状態が解除されないまま残ります。

## 詳細

- app/routes配下に、プロジェクト・サブタスクの取得と404判定を行う共通関数を置く。
- projects.py・subtasks.py・deploy.pyにある重複した判定を、共通関数に置き換える。
- ideas.pyの_github_repoとsubtasks.pyの_get_subtask_and_projectでも、プロジェクトが無い場合は404にする。
- idea_runner._repo_pathでは、worker/main.pyの_load_subtask_and_projectと同じく、原因が分かるメッセージで例外を出す。
- _create_issue_forで、GitHubClientError以外の例外でも承認中の状態を解除する。

## 根拠

app/routes/ideas.py:145はsession.get(Project, ...)の結果を確認せずに.github_repoを参照している。同じ参照はworker/idea_runner.py:42とapp/routes/subtasks.py:364にもある。ideas.py:154-158はGitHubClientErrorしか捕捉しないため、AttributeErrorではrelease_claimが呼ばれない。404判定はprojects.py:83-85,236-239、subtasks.py:254-257、deploy.py:26-28に重複している。#240ではsubtasksルート内だけをまとめており、ルートをまたいだ重複は残っている。

## 関連ファイル

- app/routes/ideas.py:143
- worker/idea_runner.py:40
- app/routes/subtasks.py:362
- app/routes/projects.py:236
- app/routes/subtasks.py:254
- app/routes/deploy.py:24
## 実行指示（2026-11-24 10:11:13 UTC）

アイデアマンの提案を実装する。

## 提案タイトル

削除済みプロジェクトを参照したときのAttributeErrorをなくし、404判定をルート間で共通化する

## 概要

プロジェクトの取得結果を確認せずに属性を参照している箇所が3つあります。承認処理では、承認中の状態が解除されないまま残ります。

## 詳細

- app/routes配下に、プロジェクト・サブタスクの取得と404判定を行う共通関数を置く。
- projects.py・subtasks.py・deploy.pyにある重複した判定を、共通関数に置き換える。
- ideas.pyの_github_repoとsubtasks.pyの_get_subtask_and_projectでも、プロジェクトが無い場合は404にする。
- idea_runner._repo_pathでは、worker/main.pyの_load_subtask_and_projectと同じく、原因が分かるメッセージで例外を出す。
- _create_issue_forで、GitHubClientError以外の例外でも承認中の状態を解除する。

## 根拠

app/routes/ideas.py:145はsession.get(Project, ...)の結果を確認せずに.github_repoを参照している。同じ参照はworker/idea_runner.py:42とapp/routes/subtasks.py:364にもある。ideas.py:154-158はGitHubClientErrorしか捕捉しないため、AttributeErrorではrelease_claimが呼ばれない。404判定はprojects.py:83-85,236-239、subtasks.py:254-257、deploy.py:26-28に重複している。#240ではsubtasksルート内だけをまとめており、ルートをまたいだ重複は残っている。

## 関連ファイル

- app/routes/ideas.py:143
- worker/idea_runner.py:40
- app/routes/subtasks.py:362
- app/routes/projects.py:236
- app/routes/subtasks.py:254
- app/routes/deploy.py:24

