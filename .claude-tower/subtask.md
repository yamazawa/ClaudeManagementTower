# サブタスク: CLI機能の追加ー③

アイデアマンの提案を実装する。

## 提案タイトル

CLIタブでは選択肢付きの質問ツールを拒否し、応答文で質問させる

## 概要

開発PCではClaudeが選択肢付きの質問（AskUserQuestion）を出すと画面で選べるが、CLIタブの許可判定は回答の無いまま許可している。画面で答えられない質問は拒否し、応答文で質問するよう促す。

## 詳細

- CLIの対話でAskUserQuestionが呼ばれたら、「質問は応答文で行い、利用者の次の発言を待つ」という理由を付けて拒否する。
- 拒否はCLIの対話の時だけにし、自律実装ワーカーの許可判定は変えない。
- CLI_DIALOG_POLICY_PROMPTの2項目目に、質問は応答文で行うことを書き足す。
- テストでは、AskUserQuestionが拒否されることと、他のツールの判定が変わらないことを確認する。
- 将来、画面に選択肢を出したくなった場合は、別のIssueで扱う。

## 根拠

core/claude_client.py:276-288 の _worktree_check は、シェル以外でパスの指定が無いツールにNoneを返す。そのため、AskUserQuestionも_to_can_use_tool（185-192行）で入力を変えずに許可される。開発PCでは利用者が選択肢を選ぶが、CLIタブには回答を受け取る経路が無い。回答が空のまま進む（または失敗する）おそれがある。core/claude_client.py:164 のポリシーでは質問してよいとしているため、このツールが使われやすい。なお、実際の挙動は実機で確認していない。

## 関連ファイル

- core/claude_client.py:160
- core/claude_client.py:185
- core/claude_client.py:276
- core/cli_session.py:188
