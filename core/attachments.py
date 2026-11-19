"""実装指示の添付ファイル管理

添付ファイルはworktree内に保存し、Claudeがworktree内の相対パスで読めるようにする。
添付ファイルはコミットしないよう、保存先にgitignoreを置く。
IDはS1、S2…の連番で、保存先のフォルダ名として保持する。
"""

import re
from pathlib import Path

ATTACHMENTS_DIR = ".claude-tower/attachments"
ATTACHMENT_ID_PREFIX = "S"
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024

_ID_PATTERN = re.compile(rf"^{ATTACHMENT_ID_PREFIX}(\d+)$")
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class AttachmentError(ValueError):
    pass


def _attachments_root(worktree_path: str) -> Path:
    return Path(worktree_path) / ATTACHMENTS_DIR


def _id_number(directory: Path) -> int | None:
    match = _ID_PATTERN.match(directory.name)
    return int(match.group(1)) if match else None


def _sanitize_filename(filename: str) -> str:
    name = _INVALID_FILENAME_CHARS.sub("_", Path(filename.replace("\\", "/")).name).strip(" .")
    if not name:
        raise AttachmentError("ファイル名が不正です")
    return name


def _to_entry(directory: Path) -> dict | None:
    files = [f for f in directory.iterdir() if f.is_file()]
    if not files:
        return None
    return {
        "id": directory.name,
        "filename": files[0].name,
        "path": f"{ATTACHMENTS_DIR}/{directory.name}/{files[0].name}",
    }


def list_attachments(worktree_path: str) -> list[dict]:
    """添付ファイルの一覧をID順に返す

    各要素はID・ファイル名・worktree内の相対パスを持つ。
    """
    root = _attachments_root(worktree_path)
    if not root.is_dir():
        return []
    directories = sorted(
        (d for d in root.iterdir() if d.is_dir() and _id_number(d) is not None),
        key=_id_number,
    )
    return [entry for entry in map(_to_entry, directories) if entry is not None]


def _ensure_root(worktree_path: str) -> Path:
    root = _attachments_root(worktree_path)
    root.mkdir(parents=True, exist_ok=True)
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")
    return root


def _next_id(root: Path) -> str:
    numbers = [n for n in map(_id_number, root.iterdir()) if n is not None]
    return f"{ATTACHMENT_ID_PREFIX}{max(numbers, default=0) + 1}"


def save_attachment(worktree_path: str, filename: str, data: bytes) -> dict:
    """添付ファイルを次のIDで保存する

    サイズ超過・不正なファイル名はAttachmentErrorとする。
    """
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise AttachmentError("ファイルサイズが上限を超えています")
    name = _sanitize_filename(filename)
    root = _ensure_root(worktree_path)
    directory = root / _next_id(root)
    directory.mkdir()
    (directory / name).write_bytes(data)
    return _to_entry(directory)


def build_instruction_prompt(instruction: str, attachments: list[dict]) -> str:
    """添付ファイルの対応表を実装指示に付け加える

    指示内のS1、S2などのIDが、どのファイルを指すかClaudeに伝える。
    """
    if not attachments:
        return instruction
    rows = "\n".join(f"| {a['id']} | {a['filename']} | {a['path']} |" for a in attachments)
    return (
        f"{instruction}\n\n"
        "## 添付ファイル\n\n"
        "指示内のS1、S2などのIDは、以下の添付ファイルを指す。\n"
        "パスはworktreeからの相対パスで、必要に応じてファイルを読んで内容を確認する。\n"
        "添付ファイルはコミットしない。\n\n"
        "| ID | ファイル名 | パス |\n"
        "| --- | --- | --- |\n"
        f"{rows}\n"
    )
