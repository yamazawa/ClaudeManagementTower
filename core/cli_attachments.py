"""CLIタブの発言の添付ファイル

CLIはリポジトリ本体のフォルダで実行するため、添付はリポジトリの外に保存する。
保存先はworktreeの置き場所の下に、CLIの項目IDごとのフォルダを作る。
この場所はClaudeの参照ルールで、読み取りは許可・書き込みは拒否される。
IDは項目内でS1、S2…の連番とし、発言をまたいで振り直さない。
"""

from pathlib import Path

from core.attachments import (
    AttachmentError,
    build_instruction_prompt,
    delete_attachment,
    find_attachment_file,
    list_attachments,
    save_attachment,
)
from core.config import settings

CLI_ATTACHMENTS_DIR_NAME = "cli-attachments"
# 項目IDのフォルダ直下にID別のフォルダを作る
CLI_ATTACHMENTS_SUBDIR = ""

ABSOLUTE_PATH_NOTE = "パスは絶対パスで、必要に応じてファイルを読んで内容を確認する。\n"


def cli_attachments_dir(cli_session_id: int) -> str:
    return str(Path(settings.worktree_base_dir) / CLI_ATTACHMENTS_DIR_NAME / str(cli_session_id))


def save_cli_attachment(cli_session_id: int, filename: str, data: bytes) -> dict:
    return save_attachment(cli_attachments_dir(cli_session_id), filename, data, CLI_ATTACHMENTS_SUBDIR)


def list_cli_attachments(cli_session_id: int) -> list[dict]:
    """保存済みの添付ファイルをID順に返す

    保存先のパスは画面に出さないため含めない。
    """
    entries = list_attachments(cli_attachments_dir(cli_session_id), CLI_ATTACHMENTS_SUBDIR)
    return [{key: value for key, value in entry.items() if key != "path"} for entry in entries]


def find_cli_attachment_file(cli_session_id: int, attachment_id: str) -> Path | None:
    return find_attachment_file(cli_attachments_dir(cli_session_id), attachment_id, CLI_ATTACHMENTS_SUBDIR)


def delete_cli_attachment(cli_session_id: int, attachment_id: str) -> bool:
    return delete_attachment(cli_attachments_dir(cli_session_id), attachment_id, CLI_ATTACHMENTS_SUBDIR)


def resolve_cli_attachments(cli_session_id: int, attachment_ids: list[str]) -> list[dict]:
    """発言に添付するIDを、パスを絶対パスにした添付の情報に変換する

    重複したIDは1件にまとめ、指定順を保つ。
    存在しないIDはAttachmentErrorとする。
    """
    base = cli_attachments_dir(cli_session_id)
    saved = {a["id"]: a for a in list_attachments(base, CLI_ATTACHMENTS_SUBDIR)}
    missing = [i for i in attachment_ids if i not in saved]
    if missing:
        raise AttachmentError(f"添付ファイルがありません: {', '.join(missing)}")
    return [{**saved[i], "path": str(Path(base) / saved[i]["path"])} for i in dict.fromkeys(attachment_ids)]


def build_cli_prompt(text: str, attachments: list[dict]) -> str:
    """添付ファイルの対応表を発言に付け加える

    MRの実装指示と同じ形で、パスのみ絶対パスとして伝える。
    """
    return build_instruction_prompt(text, attachments, ABSOLUTE_PATH_NOTE)
