import asyncio
from collections import deque
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import random
import re
from typing import Any, Awaitable, Callable, Deque, Dict, Optional, Protocol
from urllib.parse import urlparse

import websockets
import yaml

from qqbot_app.providers.composite import looks_like_wuwa_credentials


logger = logging.getLogger(__name__)


class GroupReplyProvider(Protocol):
    def answer_group(self, messages: list[str]) -> Optional[str]:
        """根据群聊文本生成无工具回答"""


@dataclass(frozen=True)
class OneBotConfig:
    enabled: bool
    ws_url: str
    access_token_env: str
    reply_probability: float
    context_messages: int
    max_message_chars: int
    reconnect_delay: float

    @classmethod
    def from_file(cls, path: Path) -> "OneBotConfig":
        if not path.exists():
            raise FileNotFoundError(f"OneBot 配置文件不存在: {path}")

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("OneBot 配置必须是 YAML 对象。")

        enabled = data.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("OneBot 配置 enabled 必须是布尔值。")
        ws_url = str(data.get("ws_url", "ws://127.0.0.1:3001")).strip()
        parsed_url = urlparse(ws_url)
        if parsed_url.scheme not in {"ws", "wss"} or not parsed_url.netloc:
            raise ValueError("OneBot 配置 ws_url 必须是有效的 ws 或 wss 地址。")
        access_token_env = str(data.get("access_token_env", "ONEBOT_ACCESS_TOKEN")).strip()
        if enabled and not access_token_env:
            raise ValueError("OneBot 配置启用时 access_token_env 不能为空。")

        return cls(
            enabled=enabled,
            ws_url=ws_url,
            access_token_env=access_token_env,
            reply_probability=_read_probability(data.get("reply_probability", 0.2)),
            context_messages=_read_positive_int(data, "context_messages", 5),
            max_message_chars=_read_positive_int(data, "max_message_chars", 500),
            reconnect_delay=_read_positive_number(data, "reconnect_delay", 5),
        )


class OneBotGroupChatClient:
    def __init__(
        self,
        config: OneBotConfig,
        access_token: str,
        responder: GroupReplyProvider,
        random_value: Callable[[], float] = random.random,
        connect: Callable[..., Any] = websockets.connect,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._access_token = access_token
        self._responder = responder
        self._random_value = random_value
        self._connect = connect
        self._sleep = sleep
        self._history: Dict[str, Deque[str]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()

    async def run(self) -> None:
        headers = {"Authorization": f"Bearer {self._access_token}"}
        try:
            while True:
                try:
                    async with self._connect(self._config.ws_url, additional_headers=headers) as websocket:
                        logger.info("OneBot WebSocket connected")
                        async for raw_message in websocket:
                            payload = _parse_payload(raw_message)
                            if payload is None:
                                continue
                            task = asyncio.create_task(self.handle_event(payload, websocket.send))
                            self._tasks.add(task)
                            task.add_done_callback(self._tasks.discard)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("OneBot WebSocket disconnected; reconnecting later")
                await self._sleep(self._config.reconnect_delay)
        finally:
            for task in self._tasks:
                task.cancel()
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)

    async def handle_event(
        self,
        payload: Dict[str, Any],
        send: Callable[[str], Awaitable[Any]],
    ) -> None:
        message = _extract_group_text(payload)
        if message is None:
            return
        group_id, text = message
        if looks_like_wuwa_credentials(text):
            logger.warning("Skipped sensitive OneBot group message")
            return

        text = text[: self._config.max_message_chars]
        history = self._history.setdefault(group_id, deque(maxlen=self._config.context_messages))
        history.append(text)
        if self._random_value() >= self._config.reply_probability:
            return

        try:
            answer = await asyncio.to_thread(self._responder.answer_group, list(history))
        except Exception:
            logger.warning("OneBot group LLM reply failed", exc_info=True)
            return
        if not answer:
            return

        request = {
            "action": "send_group_msg",
            "params": {
                "group_id": _json_id(group_id),
                "message": [{"type": "text", "data": {"text": answer}}],
            },
        }
        try:
            await send(json.dumps(request, ensure_ascii=False))
        except Exception:
            logger.warning("OneBot group message send failed", exc_info=True)


def _extract_group_text(payload: Dict[str, Any]) -> Optional[tuple[str, str]]:
    if payload.get("post_type") != "message" or payload.get("message_type") != "group":
        return None
    group_id = payload.get("group_id")
    if group_id is None:
        return None
    self_id = str(payload.get("self_id", ""))
    user_id = str(payload.get("user_id", ""))
    if self_id and user_id == self_id:
        return None

    message = payload.get("message", payload.get("raw_message", ""))
    if isinstance(message, list):
        if _segments_mention_self(message, self_id):
            return None
        text = "".join(
            str(segment.get("data", {}).get("text", ""))
            for segment in message
            if isinstance(segment, dict) and segment.get("type") == "text"
        )
    else:
        raw_text = str(message or "")
        if self_id and re.search(rf"\[CQ:at,qq={re.escape(self_id)}(?:,|\])", raw_text):
            return None
        text = re.sub(r"\[CQ:[^\]]+\]", "", raw_text)

    text = text.strip()
    if not text:
        return None
    return str(group_id), text


def _segments_mention_self(segments: list[Any], self_id: str) -> bool:
    if not self_id:
        return False
    return any(
        isinstance(segment, dict)
        and segment.get("type") == "at"
        and str(segment.get("data", {}).get("qq", "")) == self_id
        for segment in segments
    )


def _parse_payload(raw_message: Any) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(raw_message) if isinstance(raw_message, (str, bytes, bytearray)) else raw_message
    except (TypeError, ValueError):
        logger.warning("Ignored invalid OneBot payload")
        return None
    return payload if isinstance(payload, dict) else None


def _json_id(value: str) -> Any:
    return int(value) if value.isdigit() else value


def _read_probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError("OneBot 配置 reply_probability 必须是 0 到 1 之间的数字。")
    return float(value)


def _read_positive_int(data: Dict[str, Any], name: str, default: int) -> int:
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"OneBot 配置 {name} 必须是大于 0 的整数。")
    return value


def _read_positive_number(data: Dict[str, Any], name: str, default: float) -> float:
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"OneBot 配置 {name} 必须是大于 0 的数字。")
    return float(value)
