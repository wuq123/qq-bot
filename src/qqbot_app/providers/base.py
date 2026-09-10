from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol

from qqbot_app.bot_message import BotAnswer


@dataclass(frozen=True)
class AnswerContext:
    event_type: str
    raw_event: Optional[Any] = None
    extra: Dict[str, Any] = field(default_factory=dict)


class AnswerProvider(Protocol):
    def answer(self, user_id: str, text: str, context: AnswerContext) -> BotAnswer:
        """返回用户问题答案"""
        ...
