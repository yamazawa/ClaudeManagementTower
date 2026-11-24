# サブタスク: [IdeaMan] claude_client.pyを、方針プロンプト・ツール許可判定・SDK実行に分割するー①

アイデアマンの提案を実装する。

## 提案タイトル

claude_client.pyを、方針プロンプト・ツール許可判定・SDK実行に分割する

## 概要

claude_client.pyに、ツール許可判定・4種類の方針プロンプト・SDK実行処理が同居しています。責務ごとにファイルを分けて読みやすくします。

## 詳細

- AGENT・CONFLICT_RESOLUTION・CLI_DIALOG・IDEA_MANの方針プロンプトを、core/claude_prompts.pyに移す。
- 拒否判定（_shell_denial、_worktree_check、_read_only_checkなど）を、core/claude_permissions.pyに移す。
- claude_client.pyには、ClaudeAgentOptionsの組み立てと実行だけを残す。
- ロジックは変えず移動だけにする。既存テストのimport先を合わせる。
- 121-122行目にある、空行1行だけの区切りも整える。

## 根拠

core/claude_client.pyでは、1-120行目がツール許可判定、122-188行目が4種類の方針プロンプト、191-344行目がSDK実行の処理になっている。方針プロンプトを直すだけでも、セキュリティ判定のコードを読み進める必要がある。CommonGuideLineの1クラス1責務の方針にも合わない。

## 関連ファイル

- core/claude_client.py:34
- core/claude_client.py:122
- core/claude_client.py:246
- core/claude_client.py:322
