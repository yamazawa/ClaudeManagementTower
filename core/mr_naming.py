"""MR名の命名規則

MR名は「Issue名」「区切り文字」「MR固有名」を連結した形式とする。
MR固有名が空の場合は丸数字の連番を割り当てる。
"""

from collections.abc import Iterable

MR_NAME_SEPARATOR = "ー"

# 丸数字は①〜⑳・㉑〜㉟・㊱〜㊿の3ブロックに分かれて定義されている
_CIRCLED_NUMBER_RANGES = (
    (1, 20, 0x2460),
    (21, 35, 0x3251),
    (36, 50, 0x32B1),
)


def compose_mr_title(issue_title: str, suffix: str) -> str:
    return f"{issue_title}{MR_NAME_SEPARATOR}{suffix}"


def split_mr_title(issue_title: str, mr_title: str) -> str | None:
    """MR名からMR固有名を取り出す

    命名規則に沿っていない場合はNoneを返す。
    """
    prefix = f"{issue_title}{MR_NAME_SEPARATOR}"
    if not mr_title.startswith(prefix):
        return None
    suffix = mr_title[len(prefix):]
    return suffix or None


def number_label(n: int) -> str:
    """連番の表示文字列

    丸数字が無い番号は半角数字にする。
    """
    for first, last, base in _CIRCLED_NUMBER_RANGES:
        if first <= n <= last:
            return chr(base + n - first)
    return str(n)


def next_default_suffix(issue_title: str, existing_titles: Iterable[str]) -> str:
    """空欄で作成したMRに割り当てるMR固有名

    ①から順に走査し、既存MR名と重複しない最初の番号を返す。
    """
    used = set(existing_titles)
    n = 1
    while compose_mr_title(issue_title, number_label(n)) in used:
        n += 1
    return number_label(n)
