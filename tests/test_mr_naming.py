from core.mr_naming import (
    compose_mr_title,
    next_default_suffix,
    number_label,
    split_mr_title,
)


def test_compose_and_split_roundtrip():
    title = compose_mr_title("あいうえお", "かきくけこ")
    assert title == "あいうえおーかきくけこ"
    assert split_mr_title("あいうえお", title) == "かきくけこ"


def test_split_keeps_separator_inside_suffix():
    assert split_mr_title("サーバー", "サーバーーログー出力") == "ログー出力"


def test_split_returns_none_when_not_conforming():
    assert split_mr_title("あいうえお", "かきくけこ") is None
    assert split_mr_title("あいうえお", "あいうえおー") is None
    assert split_mr_title("あいうえお", "あいうえおかきくけこ") is None


def test_number_label_uses_circled_digits_then_ascii():
    assert number_label(1) == "①"
    assert number_label(20) == "⑳"
    assert number_label(21) == "㉑"
    assert number_label(35) == "㉟"
    assert number_label(36) == "㊱"
    assert number_label(50) == "㊿"
    assert number_label(51) == "51"


def test_next_default_suffix_fills_first_gap():
    existing = ["あーかきくけこ", "あー①", "あー③"]
    assert next_default_suffix("あ", existing) == "②"


def test_next_default_suffix_starts_at_one():
    assert next_default_suffix("あ", []) == "①"
