from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Optional


@dataclass(frozen=True)
class NoteCommand:
    action: str
    title: str
    content: str


class NoteService:
    def __init__(self, root: Path, max_read_chars: int = 1800) -> None:
        self._root = root
        self._max_read_chars = max_read_chars

    def create_note(self, title: str, content: str) -> str:
        path = self._note_path(title)
        if path.exists():
            return f"笔记已存在：{path.name}。如需补充内容，请使用“修改笔记”。"

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n", encoding="utf-8")
        return f"已新增笔记：{path.name}"

    def append_note(self, title: str, content: str) -> str:
        path = self._note_path(title)
        if not path.exists():
            return f"笔记不存在：{path.name}。请先使用“新增笔记”。"

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as file:
            file.write(f"\n\n## {now}\n\n{content.strip()}\n")
        return f"已追加到笔记：{path.name}"

    def list_notes(self) -> str:
        if not self._root.exists():
            return "笔记目录不存在，请检查 NOTE_ROOT。"

        notes = sorted(path.stem for path in self._root.glob("*.md") if path.is_file())
        if not notes:
            return "暂无笔记。"
        return "现有笔记：\n" + "\n".join(f"- {name}" for name in notes)

    def read_note(self, title: str) -> str:
        path = self._note_path(title)
        if not path.exists():
            return f"笔记不存在：{path.name}。"

        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return f"笔记为空：{path.name}"
        if len(content) > self._max_read_chars:
            content = content[: self._max_read_chars].rstrip() + "\n\n内容较长，已截断显示。"
        return f"{path.name}：\n{content}"

    def _note_path(self, title: str) -> Path:
        safe_title = validate_note_title(title)
        return self._root / f"{safe_title}.md"


def parse_note_command(text: str) -> Optional[NoteCommand]:
    value = _strip_mention(text)
    if value in {"笔记列表", "查询笔记列表", "查看笔记列表", "列出笔记"}:
        return NoteCommand(action="list", title="", content="")

    read_pattern = r"^(查看笔记|查询笔记|查看笔记内容|查询笔记内容|笔记内容|看笔记)[:：]\s*(.+)$"
    read_match = re.match(read_pattern, value, flags=re.DOTALL)
    if read_match:
        return NoteCommand(action="read", title=read_match.group(2).strip(), content="")

    legacy_read_pattern = r"^(查看笔记|查询笔记|查看笔记内容|查询笔记内容|笔记内容)\s+标题[:：]\s*(.+)$"
    legacy_read_match = re.match(legacy_read_pattern, value, flags=re.DOTALL)
    if legacy_read_match:
        return NoteCommand(action="read", title=legacy_read_match.group(2).strip(), content="")

    if value.startswith(("查看笔记", "查询笔记", "查看笔记内容", "查询笔记内容", "笔记内容", "看笔记")):
        return NoteCommand(action="invalid", title="", content="")

    shortcut_match = re.match(r"^(新笔记|改笔记)[:：]\s*(\S+)\s+(.+)$", value, flags=re.DOTALL)
    if shortcut_match:
        action_text, title, content = shortcut_match.groups()
        action = "create" if action_text == "新笔记" else "append"
        return NoteCommand(action=action, title=title.strip(), content=content.strip())
    if value.startswith(("新笔记", "改笔记")):
        return NoteCommand(action="invalid", title="", content="")

    pattern = r"^(新增笔记|创建笔记|修改笔记|追加笔记)\s+标题[:：]\s*(.+?)\s+内容[:：]\s*(.+)$"
    match = re.match(pattern, value, flags=re.DOTALL)
    if not match:
        if re.match(r"^(新增笔记|创建笔记|修改笔记|追加笔记)\b", value):
            return NoteCommand(action="invalid", title="", content="")
        return None

    action_text, title, content = match.groups()
    action = "create" if action_text in {"新增笔记", "创建笔记"} else "append"
    return NoteCommand(action=action, title=title.strip(), content=content.strip())


def validate_note_title(title: str) -> str:
    value = title.strip()
    if not value:
        raise ValueError("笔记标题不能为空")
    if Path(value).is_absolute() or ".." in value or "/" in value or "\\" in value:
        raise ValueError("笔记标题不能包含路径")
    if value.endswith(".md"):
        value = value[:-3].strip()
    if not value:
        raise ValueError("笔记标题不能为空")
    return value


def _strip_mention(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"<@!?\d+>", "", value)
    return value.strip()
