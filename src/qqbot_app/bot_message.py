from dataclasses import dataclass
from typing import Any, Dict, Optional, Union


@dataclass(frozen=True)
class BotMessage:
    content: str
    markdown: Optional[Dict[str, Any]] = None
    keyboard: Optional[Dict[str, Any]] = None
    image: Optional[bytes] = None


BotAnswer = Union[str, BotMessage]
