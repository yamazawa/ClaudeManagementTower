# サブタスク: 添付画像でジョブが失敗するー①

core/claude_client.pyのClaudeAgentOptionsにmax_buffer_sizeを指定し、SDKのメッセージバッファ上限（既定1MB）を緩和する。

添付画像をReadツールで読むと、Base64化された内容がSDKとCLIプロセス間のJSONメッセージとして返るため、既定の1MB上限を超えて"Failed to decode JSON: JSON message exceeded maximum buffer size"で失敗する事例がある（Issue #153 サブタスク3で確認済み）。

対応方針：
core/attachments.pyのMAX_ATTACHMENT_BYTES（添付ファイル1件あたりの上限）を使い、添付ファイル10件程度・Base64化とJSONのオーバーヘッドを見込んだ値をmax_buffer_sizeに設定する。
目安はMAX_ATTACHMENT_BYTES * 10 * 1.5程度（約300MB）。
値は定数として切り出し、根拠をコメントで残すこと。

既存テスト（pytest -k "claude_client or attachment"）が通ることを確認する。
