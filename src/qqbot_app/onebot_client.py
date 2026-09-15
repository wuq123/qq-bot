import asyncio
from collections import deque
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import random
import re
import time
from typing import Any, Awaitable, Callable, Deque, Dict, Optional, Protocol
from urllib.parse import urlparse

import websockets
import yaml

from qqbot_app.providers.composite import looks_like_wuwa_credentials
from qqbot_app.blackjack_service import BlackjackService, parse_blackjack_command
from qqbot_app.bot_message import BotAnswer, BotMessage
from qqbot_app.providers.base import AnswerContext, AnswerProvider


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
    startup_timeout_seconds: int = 10
    failover_after_failures: int = 3
    reply_cooldown_seconds: float = 30
    max_reply_chars: int = 200

    @classmethod
    def from_file(cls, path: Path) -> "OneBotConfig":
        if not path.exists():
            raise FileNotFoundError(f"OneBot 配置文件不存在: {path}")

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.from_data(data)

    @classmethod
    def from_data(cls, data: Dict[str, Any]) -> "OneBotConfig":
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
            startup_timeout_seconds=_read_positive_int(data, "startup_timeout_seconds", 10),
            failover_after_failures=_read_positive_int(data, "failover_after_failures", 3),
            reply_cooldown_seconds=_read_positive_number(data, "reply_cooldown_seconds", 30),
            max_reply_chars=_read_positive_int(data, "max_reply_chars", 200),
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
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._access_token = access_token
        self._responder = responder
        self._random_value = random_value
        self._connect = connect
        self._sleep = sleep
        self._history: Dict[str, Deque[str]] = {}
        self._replying_groups: set[str] = set()
        self._last_reply_at: Dict[str, float] = {}
        self._seen_message_keys: Deque[str] = deque(maxlen=1000)
        self._seen_message_key_set: set[str] = set()
        self._clock = clock
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
        if self._is_duplicate_message(payload, group_id):
            return
        if looks_like_wuwa_credentials(text):
            logger.warning("Skipped sensitive OneBot group message")
            return

        text = text[: self._config.max_message_chars]
        history = self._history.setdefault(group_id, deque(maxlen=self._config.context_messages))
        history.append(text)
        if group_id in self._replying_groups:
            return
        if self._clock() - self._last_reply_at.get(group_id, float("-inf")) < self._config.reply_cooldown_seconds:
            return
        if self._random_value() >= self._config.reply_probability:
            return

        self._replying_groups.add(group_id)
        try:
            try:
                answer = await asyncio.to_thread(self._responder.answer_group, list(history))
            except Exception:
                logger.warning("OneBot group LLM reply failed", exc_info=True)
                return
            answer = _safe_ambient_answer(answer, list(history), self._config.max_reply_chars)
            if answer is None:
                logger.warning("Skipped unsafe OneBot group LLM reply")
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
                return
            self._last_reply_at[group_id] = self._clock()
        finally:
            self._replying_groups.discard(group_id)

    def _is_duplicate_message(self, payload: Dict[str, Any], group_id: str) -> bool:
        message_id = payload.get("message_id")
        if message_id is None:
            return False
        key = f"{group_id}:{message_id}"
        if key in self._seen_message_key_set:
            return True
        if len(self._seen_message_keys) == self._seen_message_keys.maxlen:
            self._seen_message_key_set.discard(self._seen_message_keys[0])
        self._seen_message_keys.append(key)
        self._seen_message_key_set.add(key)
        return False


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


def _safe_ambient_answer(answer: object, context: list[str], max_chars: int) -> Optional[str]:
    value = str(answer or "").strip()
    if not value or len(value) > max_chars:
        return None
    normalized_answer = _normalize_group_text(value)
    normalized_context = [_normalize_group_text(item) for item in context if _normalize_group_text(item)]
    if not normalized_answer or normalized_answer in normalized_context:
        return None
    if len(normalized_context) > 1 and all(item in normalized_answer for item in normalized_context):
        return None
    return value


def _normalize_group_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


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


class OneBotBotClient:
    """OneBot 11 主消息入口，保留群聊随机回复。"""

    def __init__(
        self,
        config: OneBotConfig,
        access_token: str,
        provider: AnswerProvider,
        group_responder: GroupReplyProvider,
        random_value: Callable[[], float] = random.random,
        connect: Callable[..., Any] = websockets.connect,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        state_changed: Optional[Callable[[str], None]] = None,
        blackjack_service: Optional[BlackjackService] = None,
    ) -> None:
        self._config = config
        self._access_token = access_token
        self._provider = provider
        self._group_responder = group_responder
        self._random_value = random_value
        self._connect = connect
        self._sleep = sleep
        self._state_changed = state_changed or (lambda _: None)
        self._blackjack_service = blackjack_service or BlackjackService()
        self._ambient = OneBotGroupChatClient(config, access_token, group_responder, random_value)
        self._tasks: set[asyncio.Task[Any]] = set()
        self.mode = "starting"

    async def run(self) -> None:
        headers = {"Authorization": f"Bearer {self._access_token}"}
        failures = 0
        try:
            while True:
                try:
                    async with self._connect(
                        self._config.ws_url,
                        additional_headers=headers,
                        open_timeout=self._config.startup_timeout_seconds,
                    ) as websocket:
                        failures = 0
                        self._set_mode("napcat")
                        logger.info("OneBot primary WebSocket connected")
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
                    failures += 1
                    if failures >= self._config.failover_after_failures:
                        self._set_mode("botpy_fallback")
                    logger.warning("OneBot primary disconnected; reconnecting later")
                await self._sleep(self._config.reconnect_delay)
        finally:
            for task in self._tasks:
                task.cancel()
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)

    async def handle_event(self, payload: Dict[str, Any], send: Callable[[str], Awaitable[Any]]) -> None:
        if payload.get("post_type") != "message":
            return
        message_type = str(payload.get("message_type", ""))
        if message_type not in {"private", "group"}:
            return
        self_id = str(payload.get("self_id", ""))
        user_id = str(payload.get("user_id", ""))
        if self_id and user_id == self_id:
            return
        text, mentions = _extract_text_and_mentions(payload)
        if not text:
            return

        if message_type == "group":
            if _mentions_id(mentions, self_id):
                await self._answer_and_send(user_id, text, payload, "onebot_group_at", mentions, send)
                return
            if mentions:
                return
            blackjack_command = parse_blackjack_command(text)
            conversation_id = _conversation_id(payload, "onebot_group_game")
            if blackjack_command is not None and blackjack_command.action != "start" and self._blackjack_service.has_game(conversation_id):
                await self._answer_and_send(user_id, text, payload, "onebot_group_game", mentions, send)
                return
            await self._ambient.handle_event(payload, send)
            return

        await self._answer_and_send(user_id, text, payload, "onebot_private", mentions, send)

    async def _answer_and_send(
        self,
        user_id: str,
        text: str,
        payload: Dict[str, Any],
        event_type: str,
        mentions: list[str],
        send: Callable[[str], Awaitable[Any]],
    ) -> None:
        conversation_id = _conversation_id(payload, event_type)
        context = AnswerContext(
            event_type=event_type,
            raw_event=payload,
            extra={"conversation_id": conversation_id, "mention_user_ids": mentions},
        )
        blackjack_command = parse_blackjack_command(text)
        if blackjack_command is not None:
            answers = self._blackjack_service.handle_messages(user_id, blackjack_command, context)
            for answer in answers:
                await _send_onebot_answer(payload, answer, send)
            return
        else:
            try:
                answer = await asyncio.to_thread(self._provider.answer, user_id, text, context)
            except Exception:
                logger.warning("OneBot provider failed", exc_info=True)
                return
        await _send_onebot_answer(payload, answer, send)

    def _set_mode(self, mode: str) -> None:
        if self.mode != mode:
            self.mode = mode
            self._state_changed(mode)


async def _send_onebot_answer(payload: Dict[str, Any], answer: BotAnswer, send: Callable[[str], Awaitable[Any]]) -> None:
    message_type = str(payload.get("message_type", ""))
    target_key = "group_id" if message_type == "group" else "user_id"
    action = "send_group_msg" if message_type == "group" else "send_private_msg"
    target = payload.get(target_key)
    if target is None:
        return
    segments: list[Dict[str, Any]] = []
    if isinstance(answer, BotMessage):
        if answer.content and not answer.image_only:
            segments.append({"type": "text", "data": {"text": answer.content}})
        if answer.image:
            import base64

            segments.append({"type": "image", "data": {"file": f"base64://{base64.b64encode(answer.image).decode('ascii')}"}})
        if not segments and answer.content:
            segments.append({"type": "text", "data": {"text": answer.content}})
    else:
        segments.append({"type": "text", "data": {"text": str(answer)}})
    if not segments:
        return
    request = {"action": action, "params": {target_key: _json_id(str(target)), "message": segments}}
    try:
        await send(json.dumps(request, ensure_ascii=False))
    except Exception:
        logger.warning("OneBot reply send failed", exc_info=True)


def _extract_text_and_mentions(payload: Dict[str, Any]) -> tuple[str, list[str]]:
    message = payload.get("message", payload.get("raw_message", ""))
    if isinstance(message, list):
        mentions = [
            str(segment.get("data", {}).get("qq", ""))
            for segment in message
            if isinstance(segment, dict) and segment.get("type") == "at" and segment.get("data", {}).get("qq")
        ]
        text = "".join(
            str(segment.get("data", {}).get("text", ""))
            for segment in message
            if isinstance(segment, dict) and segment.get("type") == "text"
        )
        return text.strip(), mentions
    raw = str(message or "")
    mentions = re.findall(r"\[CQ:at,qq=([^,\]]+)", raw)
    return re.sub(r"\[CQ:[^\]]+\]", "", raw).strip(), mentions


def _mentions_id(mentions: list[str], user_id: str) -> bool:
    return bool(user_id and user_id in mentions)


def _conversation_id(payload: Dict[str, Any], event_type: str) -> str:
    if event_type in {"onebot_group_at", "onebot_group_game"}:
        return f"group:{payload.get('group_id', '')}"
    return f"user:{payload.get('user_id', '')}"
