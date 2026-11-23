import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.config import settings

# 見せるべきでないファイル・フォルダ名（パスのいずれかの要素に一致したら拒否）
BLOCKED_NAME_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    "*.jks",
    "*.keystore",
    "*.kdbx",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
    ".cloudflared",
    ".git-credentials",
    ".netrc",
    "_netrc",
    ".npmrc",
    ".pypirc",
    ".credentials.json",
    "credentials.json",
    "client_secret*.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    "secrets.toml",
]

# 拒否パターンに一致しても許可する名前（値を含まない雛形）
ALLOWED_NAME_PATTERNS = [".env.example", ".env.sample", ".env.template"]

PATH_SEPARATOR_PATTERN = re.compile(r"[\\/]")
SHELL_TOKEN_SEPARATOR_PATTERN = re.compile(r"[\s\"'`|&;<>(),]+")

APP_ROOT = str(Path(__file__).resolve().parents[1])


def _normalize(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def is_inside(path: str, root: str) -> bool:
    """pathがroot配下（root自身を含む）かを判定する"""
    target = _normalize(path)
    base = _normalize(root)
    return target == base or target.startswith(base.rstrip("\\/") + os.sep)


def _matches_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def is_blocked_name(name: str) -> bool:
    lowered = name.lower()
    if _matches_any(lowered, ALLOWED_NAME_PATTERNS):
        return False
    return _matches_any(lowered, BLOCKED_NAME_PATTERNS)


def is_blocked_path(path: str) -> bool:
    """パスのいずれかの要素が見せるべきでないファイル・フォルダ名かを判定する"""
    return any(is_blocked_name(part) for part in PATH_SEPARATOR_PATTERN.split(path) if part)


def command_touches_blocked(command: str) -> bool:
    """シェルコマンドに見せるべきでないファイル・フォルダを指す語が含まれるかを判定する"""
    return any(is_blocked_path(token) for token in SHELL_TOKEN_SEPARATOR_PATTERN.split(command) if token)


@dataclass
class AccessRules:
    """Claudeの参照ルール

    ReadWriteは対象worktreeを基本とし、共有ルート配下も許可する。
    共有ルート配下でも、他のworktree・管理塔自身のフォルダは書き込みを拒否する。
    見せるべきでないファイルは、場所を問わず参照・書き込みを拒否する。
    """

    worktree: str
    shared_root: str
    protected_dirs: list[str] = field(default_factory=list)

    def is_writable(self, path: str) -> bool:
        if is_blocked_path(path):
            return False
        if is_inside(path, self.worktree):
            return True
        if any(is_inside(path, protected) for protected in self.protected_dirs):
            return False
        return is_inside(path, self.shared_root)


def default_access_rules(worktree: str) -> AccessRules:
    return AccessRules(
        worktree=worktree,
        shared_root=settings.claude_shared_root,
        protected_dirs=[settings.worktree_base_dir, APP_ROOT],
    )
