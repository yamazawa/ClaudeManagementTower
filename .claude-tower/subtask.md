# サブタスク: CLIタブで参照禁止ファイルへの操作も許可問い合わせの上で実行するー①

CLIタブ（ask_outside_worktree）で、参照禁止ファイルに触れる操作を拒否から許可問い合わせに変える。

- core/claude_permissions.py の ask_outside_worktree で、_blocked_check を拒否判定から外し、問い合わせ判定（ask_check）に含める。
- 参照禁止ファイルの問い合わせ理由は、参照禁止ファイルである旨と、許可すると内容がClaudeの文脈・会話ログに入る旨が分かる文言にする。文言は集約先に置く。
- 参照禁止と範囲外の両方に該当する場合は、参照禁止の理由を優先して表示する。
- AskUserQuestion（denied_tools）は従来通り問い合わせずに拒否する。
- restrict_to_worktree・restrict_to_read_only（ワーカー・アイデアマン）の挙動は変えない。
- tests/test_claude_client.py 等の既存テストを更新し、CLIタブでの参照禁止ファイル（Read・Bash）が ask になること、ワーカーでは deny のままであることを確認するテストを追加する。
- IMPLEMENTATION_PLAN.md 8章「CLIタブの許可問い合わせ」の表 No.1・No.2 を更新する。
- CLAUDE.md の「秘密鍵・.env・認証情報ファイル等は、場所を問わず参照・書き込みが拒否される」に、CLIタブでは問い合わせになる旨を追記する。
