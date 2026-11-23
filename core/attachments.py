"""実装指示の添付ファイル管理

添付ファイルはworktree内に保存し、Claudeがworktree内の相対パスで読めるようにする。
添付ファイルはコミットしないよう、保存先にgitignoreを置く。
IDはS1、S2…の連番で、保存先のフォルダ名として保持する。
保存先は基準フォルダからの相対パス（subdir）で変えられる。
"""

import re
from pathlib import Path

ATTACHMENTS_DIR = ".claude-tower/attachments"
ATTACHMENT_ID_PREFIX = "S"
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

# 指示文で伝える添付ファイルのパスの扱い（worktree内に保存する場合）
WORKTREE_PATH_NOTE = (
    "パスはworktreeからの相対パスで、必要に応じてファイルを読んで内容を確認する。\n"
    "添付ファイルはコミットしない。\n"
)

_ID_PATTERN = re.compile(rf"^{ATTACHMENT_ID_PREFIX}(\d+)$")
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class AttachmentError(ValueError):
    pass


def _attachments_root(worktree_path: str, subdir: str = ATTACHMENTS_DIR) -> Path:
    return Path(worktree_path) / subdir


def _id_number(directory: Path) -> int | None:
    match = _ID_PATTERN.match(directory.name)
    return int(match.group(1)) if match else None


def _sanitize_filename(filename: str) -> str:
    name = _INVALID_FILENAME_CHARS.sub("_", Path(filename.replace("\\", "/")).name).strip(" .")
    if not name:
        raise AttachmentError("ファイル名が不正です")
    return name


def _to_entry(directory: Path, base: Path) -> dict | None:
    files = [f for f in directory.iterdir() if f.is_file()]
    if not files:
        return None
    return {
        "id": directory.name,
        "filename": files[0].name,
        "path": files[0].relative_to(base).as_posix(),
        "is_image": files[0].suffix.lower() in IMAGE_EXTENSIONS,
    }


def list_attachments(worktree_path: str, subdir: str = ATTACHMENTS_DIR) -> list[dict]:
    """添付ファイルの一覧をID順に返す

    各要素はID・ファイル名・基準フォルダからの相対パス・画像かどうかを持つ。
    """
    root = _attachments_root(worktree_path, subdir)
    if not root.is_dir():
        return []
    directories = sorted(
        (d for d in root.iterdir() if d.is_dir() and _id_number(d) is not None),
        key=_id_number,
    )
    entries = [_to_entry(d, Path(worktree_path)) for d in directories]
    return [entry for entry in entries if entry is not None]


def find_attachment_file(worktree_path: str, attachment_id: str, subdir: str = ATTACHMENTS_DIR) -> Path | None:
    """IDに対応する添付ファイルの実パスを返す

    IDの形式が不正、またはファイルが無い場合はNoneを返す。
    """
    if not _ID_PATTERN.match(attachment_id):
        return None
    directory = _attachments_root(worktree_path, subdir) / attachment_id
    if not directory.is_dir():
        return None
    files = [f for f in directory.iterdir() if f.is_file()]
    return files[0] if files else None


def _ensure_root(worktree_path: str, subdir: str) -> Path:
    root = _attachments_root(worktree_path, subdir)
    root.mkdir(parents=True, exist_ok=True)
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")
    return root


def _next_id(root: Path) -> str:
    numbers = [n for n in map(_id_number, root.iterdir()) if n is not None]
    return f"{ATTACHMENT_ID_PREFIX}{max(numbers, default=0) + 1}"


def save_attachment(worktree_path: str, filename: str, data: bytes, subdir: str = ATTACHMENTS_DIR) -> dict:
    """添付ファイルを次のIDで保存する

    サイズ超過・不正なファイル名はAttachmentErrorとする。
    """
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise AttachmentError("ファイルサイズが上限を超えています")
    name = _sanitize_filename(filename)
    root = _ensure_root(worktree_path, subdir)
    directory = root / _next_id(root)
    directory.mkdir()
    (directory / name).write_bytes(data)
    return _to_entry(directory, Path(worktree_path))


def delete_attachment(worktree_path: str, attachment_id: str, subdir: str = ATTACHMENTS_DIR) -> bool:
    """IDに対応する添付ファイルを保存先フォルダごと削除する

    IDの形式が不正、または添付ファイルが無い場合はFalseを返す。
    フォルダ直下のファイルのみ削除し、サブフォルダは辿らない。
    """
    if not _ID_PATTERN.match(attachment_id):
        return False
    directory = _attachments_root(worktree_path, subdir) / attachment_id
    if not directory.is_dir():
        return False
    for file in (f for f in directory.iterdir() if f.is_file()):
        file.unlink()
    directory.rmdir()
    return True


def build_instruction_prompt(instruction: str, attachments: list[dict], path_note: str = WORKTREE_PATH_NOTE) -> str:
    """添付ファイルの対応表を実装指示に付け加える

    指示内のS1、S2などのIDが、どのファイルを指すかClaudeに伝える。
    パスの説明は、添付の保存先に合わせて呼び出し側で変えられる。
    """
    if not attachments:
        return instruction
    rows = "\n".join(f"| {a['id']} | {a['filename']} | {a['path']} |" for a in attachments)
    return (
        f"{instruction}\n\n"
        "## 添付ファイル\n\n"
        "指示内のS1、S2などのIDは、以下の添付ファイルを指す。\n"
        f"{path_note}\n"
        "| ID | ファイル名 | パス |\n"
        "| --- | --- | --- |\n"
        f"{rows}\n"
    )
