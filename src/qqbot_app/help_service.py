from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union

import yaml

from qqbot_app.bot_message import BotMessage


@dataclass(frozen=True)
class HelpFeature:
    key: str
    title: str
    aliases: List[str] = field(default_factory=list)
    summary: str = ""
    requirements: List[str] = field(default_factory=list)
    commands: List[str] = field(default_factory=list)
    buttons: List[Dict[str, Union[str, bool]]] = field(default_factory=list)


class HelpService:
    def __init__(self, features: List[HelpFeature], title: str = "功能帮助") -> None:
        self._features = features
        self._title = title

    @classmethod
    def from_file(cls, path: Path) -> "HelpService":
        if not path.exists():
            raise FileNotFoundError(f"帮助配置文件不存在: {path}")

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        features = [_parse_feature(item) for item in data.get("features", [])]
        return cls(features=features, title=str(data.get("title", "功能帮助")).strip() or "功能帮助")

    def answer(self, text: str) -> Optional[BotMessage]:
        value = _normalize_help_text(text)
        if value.lower() not in {"帮助", "help", "/help"} and not value.startswith("帮助 "):
            return None

        topic = value[3:].strip() if value.startswith("帮助 ") else ""
        if not topic or topic.lower() in {"help", "/help"}:
            return self._feature_list_message()

        feature = self._find_feature(topic)
        if feature is None:
            return self._unknown_feature_message(topic)
        return self._feature_detail_message(feature)

    def _feature_list_message(self) -> BotMessage:
        lines = [self._title, "点击下方功能按钮查看用法；也可以直接输入："]
        lines.extend(f"- 帮助 {feature.title}" for feature in self._features)
        content = "\n".join(lines)
        buttons = [{"label": feature.title, "command": f"帮助 {feature.title}"} for feature in self._features]
        return _rich_message(content, buttons)

    def _unknown_feature_message(self, topic: str) -> BotMessage:
        names = "、".join(feature.title for feature in self._features) or "暂无"
        content = f"没有找到“{topic}”的帮助。\n可用功能：{names}\n发送：帮助 <功能名>"
        buttons = [{"label": feature.title, "command": f"帮助 {feature.title}"} for feature in self._features]
        return _rich_message(content, buttons)

    def _feature_detail_message(self, feature: HelpFeature) -> BotMessage:
        lines = [feature.title]
        if feature.summary:
            lines.append(feature.summary)
        if feature.requirements:
            lines.append("需求：")
            lines.extend(f"- {item}" for item in feature.requirements)
        if feature.commands:
            lines.append("触发方式：")
            lines.extend(f"- {item}" for item in feature.commands)

        buttons = feature.buttons or [{"label": command, "command": command} for command in feature.commands[:5]]
        return _rich_message("\n".join(lines), buttons)

    def _find_feature(self, topic: str) -> Optional[HelpFeature]:
        target = topic.strip().lower()
        for feature in self._features:
            names = [feature.key, feature.title, *feature.aliases]
            if target in {str(name).strip().lower() for name in names}:
                return feature
        return None


def _parse_feature(item: Dict[str, Any]) -> HelpFeature:
    return HelpFeature(
        key=str(item.get("key", "")).strip(),
        title=str(item.get("title", "")).strip(),
        aliases=[str(value).strip() for value in item.get("aliases", []) if str(value).strip()],
        summary=str(item.get("summary", "")).strip(),
        requirements=[str(value).strip() for value in item.get("requirements", []) if str(value).strip()],
        commands=[str(value).strip() for value in item.get("commands", []) if str(value).strip()],
        buttons=[_parse_button(value) for value in item.get("buttons", [])],
    )


def _parse_button(item: Dict[str, Any]) -> Dict[str, Union[str, bool]]:
    return {
        "label": str(item.get("label", "")).strip(),
        "command": str(item.get("command", "")).strip(),
        "enter": bool(item.get("enter", True)),
    }


def _rich_message(content: str, buttons: List[Dict[str, Union[str, bool]]]) -> BotMessage:
    valid_buttons = [button for button in buttons if button.get("label") and button.get("command")]
    return BotMessage(
        content=content,
        markdown={"content": content},
        keyboard={"content": {"rows": _keyboard_rows(valid_buttons)}},
    )


def _keyboard_rows(buttons: List[Dict[str, Union[str, bool]]]) -> List[Dict[str, Any]]:
    rows = []
    for index in range(0, len(buttons), 2):
        row_buttons = [_keyboard_button(index + offset, button) for offset, button in enumerate(buttons[index : index + 2])]
        if row_buttons:
            rows.append({"buttons": row_buttons})
    return rows


def _keyboard_button(index: int, button: Dict[str, Union[str, bool]]) -> Dict[str, Any]:
    label = str(button["label"])
    return {
        "id": f"help_{index}",
        "render_data": {"label": label, "visited_label": label, "style": 1},
        "action": {
            "type": 2,
            "permission": {"type": 2, "specify_role_ids": [], "specify_user_ids": []},
            "click_limit": 0,
            "data": str(button["command"]),
            "at_bot_show_channel_list": False,
            "enter": bool(button.get("enter", True)),
            "reply": False,
        },
    }


def _normalize_help_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"<@!?\d+>", "", value)
    return value.strip()
