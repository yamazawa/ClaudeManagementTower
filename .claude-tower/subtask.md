# サブタスク: Claude参照ルールー③

アイデアマンの提案を実装する。

## 提案タイトル

[SPn]タスクn - worktree内判定の前方一致・大文字小文字の不備を修正

## 概要

書き込み先のパス判定が単純な前方一致です。そのため、名前の先頭が同じ別フォルダを誤って許可したり、大文字小文字の違いで誤って拒否したりします。

## 詳細

パスの包含判定を共通関数（os.path.normcaseとos.path.commonpathを使う）に1本化します。
restrict_to_worktree・_is_inside・_command_escapes_worktreeから、この関数を使うようにします。
アイデアマン用のチェックは今のところfile_pathとpathしか見ていません。Glob・Grepのpatternやglobに絶対パスを指定した場合も判定対象にします。
名前の先頭が同じ別フォルダ、大文字小文字の違い、絶対パスのpatternのテストを追加します。

## 根拠

core/claude_client.py:186はnormcaseなしのstartswithのため、大文字小文字だけ違うパスを拒否し、名前の先頭が同じ別フォルダを許可します。
core/claude_client.py:46,114はlower()の後に前方一致で比べるため、名前の先頭が同じ別フォルダを許可します。
core/claude_client.py:127はfile_pathとpathしか確認していません。
#180-①の実行レポートで「書き込み先のパス判定が前方一致」の既存不具合として挙がっていましたが、未修正のままです。

## 関連ファイル

- core/claude_client.py:40
- core/claude_client.py:113
- core/claude_client.py:127
- core/claude_client.py:186
