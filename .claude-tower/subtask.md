# サブタスク: Claude参照ルールー④

アイデアマンの提案を実装する。

## 提案タイトル

[SPn]タスクn - 読み取り専用ツール名の定数が二重定義され外部参照許可が一部効かない

## 概要

READ_ONLY_TOOL_NAMESが2回定義され、後の定義（Read・Glob・Grepのみ）で上書きされています。そのため、#180で許可したLS・NotebookReadのworktree外参照が拒否されます。

## 詳細

worktree用（外部参照を許可する読み取りツール）とアイデアマン用（SDKのtoolsに渡す一覧）で、定数名を分けます。
restrict_to_worktreeは、LS・NotebookReadを含む集合を参照するよう修正します。
worktree外のパスを指定したLS・NotebookReadが許可されるテストを追加します。

## 根拠

core/claude_client.py:24で集合として定義した後、core/claude_client.py:110で同じ名前のリストとして再定義しています。
core/claude_client.py:182の判定は実行時にモジュール変数を参照するため、110行目の値が使われます。
tests/test_claude_client.py:66,71はRead・Glob・Grepだけを確認しており、LS・NotebookReadのテストはありません。

## 関連ファイル

- core/claude_client.py:24
- core/claude_client.py:110
- core/claude_client.py:182
- tests/test_claude_client.py:71
- tests/test_claude_client.py:146
## 実行指示（2026-11-23 04:38:10 UTC）

アイデアマンの提案を実装する。

## 提案タイトル

[SPn]タスクn - 読み取り専用ツール名の定数が二重定義され外部参照許可が一部効かない

## 概要

READ_ONLY_TOOL_NAMESが2回定義され、後の定義（Read・Glob・Grepのみ）で上書きされています。そのため、#180で許可したLS・NotebookReadのworktree外参照が拒否されます。

## 詳細

worktree用（外部参照を許可する読み取りツール）とアイデアマン用（SDKのtoolsに渡す一覧）で、定数名を分けます。
restrict_to_worktreeは、LS・NotebookReadを含む集合を参照するよう修正します。
worktree外のパスを指定したLS・NotebookReadが許可されるテストを追加します。

## 根拠

core/claude_client.py:24で集合として定義した後、core/claude_client.py:110で同じ名前のリストとして再定義しています。
core/claude_client.py:182の判定は実行時にモジュール変数を参照するため、110行目の値が使われます。
tests/test_claude_client.py:66,71はRead・Glob・Grepだけを確認しており、LS・NotebookReadのテストはありません。

## 関連ファイル

- core/claude_client.py:24
- core/claude_client.py:110
- core/claude_client.py:182
- tests/test_claude_client.py:71
- tests/test_claude_client.py:146

