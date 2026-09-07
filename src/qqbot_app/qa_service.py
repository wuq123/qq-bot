from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, List, Optional

import yaml

from qqbot_app.providers import AnswerContext, AnswerProvider


@dataclass(frozen=True)
class FaqItem:
    question: str
    answer: str
    keywords: List[str] = field(default_factory=list)


class FaqAnswerProvider(AnswerProvider):
    def __init__(
        self,
        items: List[FaqItem],
        fallback_answer: str,
        empty_answer: str,
        help_answer: Optional[str] = None,
    ) -> None:
        self._items = items
        self._fallback_answer = fallback_answer
        self._empty_answer = empty_answer
        self._help_answer = help_answer

    @classmethod
    def from_file(cls, path: Path) -> "FaqAnswerProvider":
        if not path.exists():
            raise FileNotFoundError(f"FAQ 配置文件不存在: {path}")

        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}

        items = [_parse_faq_item(item) for item in data.get("items", [])]
        return cls(
            items=items,
            fallback_answer=str(data.get("fallback_answer", "暂时没有找到合适答案。你可以输入“帮助”查看可提问的问题。")),
            empty_answer=str(data.get("empty_answer", "请发送具体问题，我会尽量回答。")),
            help_answer=data.get("help_answer"),
        )

    def answer(self, user_id: str, text: str, context: AnswerContext) -> str:
        normalized_text = _normalize_text(text)
        if not normalized_text:
            return self._empty_answer

        if normalized_text.lower() in {"帮助", "help", "/help"}:
            return self._build_help_answer()

        for item in self._items:
            if normalized_text == _normalize_text(item.question):
                return item.answer

        lowered_text = normalized_text.lower()
        for item in self._items:
            for keyword in item.keywords:
                if _normalize_text(keyword).lower() in lowered_text:
                    return item.answer

        return self._fallback_answer

    def _build_help_answer(self) -> str:
        if self._help_answer:
            return self._help_answer
        questions = [item.question for item in self._items[:5]]
        if not questions:
            return self._fallback_answer
        return "你可以问：" + "、".join(questions)


def _parse_faq_item(item: dict[str, Any]) -> FaqItem:
    return FaqItem(
        question=str(item.get("question", "")).strip(),
        answer=str(item.get("answer", "")).strip(),
        keywords=[str(keyword).strip() for keyword in item.get("keywords", []) if str(keyword).strip()],
    )


def _normalize_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"<@!?\d+>", "", value)
    return value.strip()
