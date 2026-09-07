import logging
from typing import Any

import botpy

from qqbot_app.providers import AnswerContext, AnswerProvider

logger = logging.getLogger(__name__)


class QQQuestionAnswerBot(botpy.Client):
    def __init__(self, answer_provider: AnswerProvider, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._answer_provider = answer_provider

    async def on_ready(self) -> None:
        logger.info("QQ bot ready: %s", getattr(self.robot, "name", "unknown"))

    async def on_at_message_create(self, message: Any) -> None:
        await self._answer_and_reply(message, "at_message")

    async def on_c2c_message_create(self, message: Any) -> None:
        await self._answer_and_reply(message, "c2c_message")

    async def on_group_at_message_create(self, message: Any) -> None:
        await self._answer_and_reply(message, "group_at_message")

    async def _answer_and_reply(self, message: Any, event_type: str) -> None:
        text = str(getattr(message, "content", "") or "")
        user_id = _extract_user_id(message)
        context = AnswerContext(event_type=event_type, raw_event=message)
        answer = self._answer_provider.answer(user_id=user_id, text=text, context=context)
        await _send_reply(message, event_type, answer)


async def _send_reply(message: Any, event_type: str, answer: str) -> None:
    reply = getattr(message, "reply", None)
    if callable(reply):
        await reply(content=answer)
        return

    api = getattr(message, "_api", None)
    if api is None:
        raise RuntimeError(f"无法发送回复，消息对象缺少 reply 或 _api: {event_type}")

    message_id = getattr(message, "id", None)
    if event_type == "c2c_message" and hasattr(api, "post_c2c_message"):
        openid = _extract_openid(message)
        await api.post_c2c_message(openid=openid, msg_type=0, msg_id=message_id, content=answer)
        return

    if event_type == "group_at_message" and hasattr(api, "post_group_message"):
        group_openid = getattr(message, "group_openid", None)
        await api.post_group_message(group_openid=group_openid, msg_type=0, msg_id=message_id, content=answer)
        return

    raise RuntimeError(f"当前 SDK 消息对象不支持回复事件: {event_type}")


def _extract_user_id(message: Any) -> str:
    author = getattr(message, "author", None)
    for value in (
        getattr(author, "id", None),
        getattr(author, "user_openid", None),
        getattr(message, "user_openid", None),
        getattr(message, "openid", None),
    ):
        if value:
            return str(value)
    return "unknown"


def _extract_openid(message: Any) -> str:
    author = getattr(message, "author", None)
    for value in (
        getattr(author, "user_openid", None),
        getattr(message, "user_openid", None),
        getattr(message, "openid", None),
    ):
        if value:
            return str(value)
    raise RuntimeError("无法从 C2C 消息中读取用户 openid")
