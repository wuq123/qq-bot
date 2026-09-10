from pathlib import Path

import pytest

from qqbot_app.note_service import NoteService, parse_note_command, validate_note_title


def test_create_note_success(tmp_path: Path) -> None:
    service = NoteService(tmp_path)

    result = service.create_note("Git", "第一条笔记")

    assert result == "已新增笔记：Git.md"
    assert (tmp_path / "Git.md").read_text(encoding="utf-8") == "第一条笔记\n"


def test_create_existing_note_returns_conflict(tmp_path: Path) -> None:
    (tmp_path / "Git.md").write_text("旧内容\n", encoding="utf-8")
    service = NoteService(tmp_path)

    result = service.create_note("Git", "新内容")

    assert "笔记已存在" in result
    assert (tmp_path / "Git.md").read_text(encoding="utf-8") == "旧内容\n"


def test_append_note_success(tmp_path: Path) -> None:
    (tmp_path / "Git.md").write_text("旧内容\n", encoding="utf-8")
    service = NoteService(tmp_path)

    result = service.append_note("Git", "追加内容")
    content = (tmp_path / "Git.md").read_text(encoding="utf-8")

    assert result == "已追加到笔记：Git.md"
    assert "旧内容" in content
    assert "追加内容" in content


def test_append_missing_note_returns_tip(tmp_path: Path) -> None:
    service = NoteService(tmp_path)

    result = service.append_note("Git", "追加内容")

    assert result == "笔记不存在：Git.md。请先使用“新增笔记”。"


def test_list_notes(tmp_path: Path) -> None:
    (tmp_path / "Vue.md").write_text("Vue", encoding="utf-8")
    (tmp_path / "Git.md").write_text("Git", encoding="utf-8")
    (tmp_path / "Other.txt").write_text("Other", encoding="utf-8")
    service = NoteService(tmp_path)

    result = service.list_notes()

    assert result == "现有笔记：\n- Git\n- Vue"


def test_list_notes_empty(tmp_path: Path) -> None:
    service = NoteService(tmp_path)

    assert service.list_notes() == "暂无笔记。"


def test_read_note(tmp_path: Path) -> None:
    (tmp_path / "Git.md").write_text("Git 内容", encoding="utf-8")
    service = NoteService(tmp_path)

    assert service.read_note("Git") == "Git.md：\nGit 内容"


def test_read_note_accepts_md_suffix(tmp_path: Path) -> None:
    (tmp_path / "Git.md").write_text("Git 内容", encoding="utf-8")
    service = NoteService(tmp_path)

    assert service.read_note("Git.md") == "Git.md：\nGit 内容"


def test_read_missing_note_returns_tip(tmp_path: Path) -> None:
    service = NoteService(tmp_path)

    assert service.read_note("Git") == "笔记不存在：Git.md。"


def test_read_long_note_is_truncated(tmp_path: Path) -> None:
    (tmp_path / "Git.md").write_text("abcdef", encoding="utf-8")
    service = NoteService(tmp_path, max_read_chars=3)

    result = service.read_note("Git")

    assert result == "Git.md：\nabc\n\n内容较长，已截断显示。"


@pytest.mark.parametrize("title", ["", "  ", "../Git", "a/b", "a\\b", "C:\\notes\\Git"])
def test_invalid_title_rejected(title: str) -> None:
    with pytest.raises(ValueError):
        validate_note_title(title)


def test_parse_create_command() -> None:
    command = parse_note_command("新增笔记 标题：Git 内容：这里是内容")

    assert command is not None
    assert command.action == "create"
    assert command.title == "Git"
    assert command.content == "这里是内容"


def test_parse_append_command_after_mention() -> None:
    command = parse_note_command("<@!123> 修改笔记 标题：Git 内容：追加内容")

    assert command is not None
    assert command.action == "append"
    assert command.title == "Git"
    assert command.content == "追加内容"


def test_parse_list_command() -> None:
    command = parse_note_command("查询笔记列表")

    assert command is not None
    assert command.action == "list"


def test_parse_read_command() -> None:
    command = parse_note_command("查询笔记内容：Git")

    assert command is not None
    assert command.action == "read"
    assert command.title == "Git"


def test_parse_short_read_command() -> None:
    command = parse_note_command("看笔记：Git")

    assert command is not None
    assert command.action == "read"
    assert command.title == "Git"


def test_parse_short_create_command() -> None:
    command = parse_note_command("新笔记：Git 这里是内容")

    assert command is not None
    assert command.action == "create"
    assert command.title == "Git"
    assert command.content == "这里是内容"


def test_parse_short_append_command() -> None:
    command = parse_note_command("改笔记：Git 追加内容")

    assert command is not None
    assert command.action == "append"
    assert command.title == "Git"
    assert command.content == "追加内容"


def test_parse_legacy_read_command() -> None:
    command = parse_note_command("查看笔记 标题：Git")

    assert command is not None
    assert command.action == "read"
    assert command.title == "Git"


def test_parse_invalid_note_command() -> None:
    command = parse_note_command("新增笔记 Git 这里是内容")

    assert command is not None
    assert command.action == "invalid"
