import pytest

from core.attachments import (
    MAX_ATTACHMENT_BYTES,
    AttachmentError,
    build_instruction_prompt,
    find_attachment_file,
    list_attachments,
    save_attachment,
)


def test_save_attachment_assigns_sequential_ids(tmp_path):
    first = save_attachment(str(tmp_path), "a.png", b"1")
    second = save_attachment(str(tmp_path), "b.txt", b"2")

    assert first == {
        "id": "S1",
        "filename": "a.png",
        "path": ".claude-tower/attachments/S1/a.png",
        "is_image": True,
    }
    assert second["id"] == "S2"
    assert (tmp_path / ".claude-tower/attachments/S2/b.txt").read_bytes() == b"2"


def test_save_attachment_ignores_attachments_in_git(tmp_path):
    save_attachment(str(tmp_path), "a.png", b"1")

    assert (tmp_path / ".claude-tower/attachments/.gitignore").read_text(encoding="utf-8") == "*\n"


def test_save_attachment_strips_directory_from_filename(tmp_path):
    entry = save_attachment(str(tmp_path), "..\\..\\evil.txt", b"1")

    assert entry["filename"] == "evil.txt"
    assert (tmp_path / ".claude-tower/attachments/S1/evil.txt").exists()


def test_save_attachment_rejects_empty_filename(tmp_path):
    with pytest.raises(AttachmentError):
        save_attachment(str(tmp_path), "..", b"1")


def test_save_attachment_rejects_too_large_file(tmp_path):
    with pytest.raises(AttachmentError):
        save_attachment(str(tmp_path), "a.bin", b"0" * (MAX_ATTACHMENT_BYTES + 1))


def test_list_attachments_orders_by_id_number(tmp_path):
    for i in range(10):
        save_attachment(str(tmp_path), f"f{i}.txt", b"x")

    ids = [a["id"] for a in list_attachments(str(tmp_path))]

    assert ids == [f"S{i}" for i in range(1, 11)]


def test_list_attachments_without_directory_is_empty(tmp_path):
    assert list_attachments(str(tmp_path)) == []


def test_build_instruction_prompt_without_attachments_is_unchanged():
    assert build_instruction_prompt("指示", []) == "指示"


def test_build_instruction_prompt_appends_attachment_table(tmp_path):
    attachments = [save_attachment(str(tmp_path), "画面.png", b"1")]

    prompt = build_instruction_prompt("S1の画面を直して", attachments)

    assert prompt.startswith("S1の画面を直して\n")
    assert "| S1 | 画面.png | .claude-tower/attachments/S1/画面.png |" in prompt


def test_save_attachment_marks_only_images(tmp_path):
    assert save_attachment(str(tmp_path), "a.JPG", b"1")["is_image"] is True
    assert save_attachment(str(tmp_path), "b.txt", b"1")["is_image"] is False


def test_find_attachment_file_returns_saved_file(tmp_path):
    save_attachment(str(tmp_path), "a.png", b"1")

    assert find_attachment_file(str(tmp_path), "S1").read_bytes() == b"1"


@pytest.mark.parametrize("attachment_id", ["S2", "..", "S1/../S1", "X1"])
def test_find_attachment_file_rejects_unknown_or_invalid_id(tmp_path, attachment_id):
    save_attachment(str(tmp_path), "a.png", b"1")

    assert find_attachment_file(str(tmp_path), attachment_id) is None
