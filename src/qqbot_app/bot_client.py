import logging
from typing import Any

import botpy

from qqbot_app.providers import AnswerContext, AnswerProvider, BotAnswer, BotMessage

logger = logging.getLogger(__name__)


class QQQuestionAnswerBot(botpy.Client):
    def __init__(self, answer_provider: AnswerProvider, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._answer_provider = answer_provider

    async def on_ready(self) -> None:
        robot_name = getattr(self.robot, "name", "unknown")
        print(f"bot debug: ready robot={robot_name}", flush=True)
        logger.info("QQ bot ready: %s", robot_name)

    async def on_at_message_create(self, message: Any) -> None:
        await self._answer_and_reply(message, "at_message")

    async def on_c2c_message_create(self, message: Any) -> None:
        await self._answer_and_reply(message, "c2c_message")

    async def on_direct_message_create(self, message: Any) -> None:
        await self._answer_and_reply(message, "direct_message")

    async def on_group_at_message_create(self, message: Any) -> None:
        await self._answer_and_reply(message, "group_at_message")

    async def on_group_add_robot(self, event: Any) -> None:
        group_openid = getattr(event, "group_openid", None)
        print(f"bot debug: event_type=group_add_robot group_openid={group_openid}", flush=True)
        logger.info("group add robot: group_openid=%s", group_openid)

    async def on_group_msg_receive(self, event: Any) -> None:
        group_openid = getattr(event, "group_openid", None)
        print(f"bot debug: event_type=group_msg_receive group_openid={group_openid}", flush=True)
        logger.info("group msg receive: group_openid=%s", group_openid)

    async def on_group_msg_reject(self, event: Any) -> None:
        group_openid = getattr(event, "group_openid", None)
        print(f"bot debug: event_type=group_msg_reject group_openid={group_openid}", flush=True)
        logger.info("group msg reject: group_openid=%s", group_openid)

    async def on_friend_add(self, event: Any) -> None:
        user_id = _extract_user_id(event)
        print(f"bot debug: event_type=friend_add user_id={user_id}", flush=True)
        logger.info("friend add: user_id=%s", user_id)

    async def on_c2c_msg_receive(self, event: Any) -> None:
        user_id = _extract_user_id(event)
        print(f"bot debug: event_type=c2c_msg_receive user_id={user_id}", flush=True)
        logger.info("c2c msg receive: user_id=%s", user_id)

    async def on_c2c_msg_reject(self, event: Any) -> None:
        user_id = _extract_user_id(event)
        print(f"bot debug: event_type=c2c_msg_reject user_id={user_id}", flush=True)
        logger.info("c2c msg reject: user_id=%s", user_id)

    async def _answer_and_reply(self, message: Any, event_type: str) -> None:
        text = str(getattr(message, "content", "") or "")
        user_id = _extract_user_id(message)
        print(f"bot debug: event_type={event_type} user_id={user_id}", flush=True)
        logger.info("received message: event_type=%s user_id=%s", event_type, user_id)
        context = AnswerContext(event_type=event_type, raw_event=message, extra={"mention_user_ids": _extract_mention_user_ids(message)})
        answer = self._answer_provider.answer(user_id=user_id, text=text, context=context)
        logger.info("answer generated: event_type=%s answer_type=%s", event_type, type(answer).__name__)
        await _send_reply(message, event_type, answer)


async def _send_reply(message: Any, event_type: str, answer: BotAnswer) -> None:
    payload = _build_payload(answer)
    try:
        await _send_payload(message, event_type, payload)
    except Exception:
        if not isinstance(answer, BotMessage) or not (answer.markdown or answer.keyboard):
            logger.exception("reply failed: event_type=%s", event_type)
            raise
        logger.warning("rich message failed, fallback to text", exc_info=True)
        await _send_payload(message, event_type, {"content": answer.content})


async def _send_payload(message: Any, event_type: str, payload: dict[str, Any]) -> None:
    reply = getattr(message, "reply", None)
    if callable(reply):
        reply_payload = dict(payload)
        if event_type not in {"c2c_message", "group_at_message"}:
            reply_payload.pop("msg_type", None)
        await reply(**reply_payload)
        return

    api = getattr(message, "_api", None)
    if api is None:
        raise RuntimeError(f"无法发送回复，消息对象缺少 reply 或 _api: {event_type}")

    message_id = getattr(message, "id", None)
    api_payload = dict(payload)
    msg_type = api_payload.pop("msg_type", 0)
    if event_type == "c2c_message" and hasattr(api, "post_c2c_message"):
        openid = _extract_openid(message)
        await api.post_c2c_message(openid=openid, msg_type=msg_type, msg_id=message_id, **api_payload)
        return

    if event_type == "group_at_message" and hasattr(api, "post_group_message"):
        group_openid = getattr(message, "group_openid", None)
        await api.post_group_message(group_openid=group_openid, msg_type=msg_type, msg_id=message_id, **api_payload)
        return

    raise RuntimeError(f"当前 SDK 消息对象不支持回复事件: {event_type}")


def _build_payload(answer: BotAnswer) -> dict[str, Any]:
    if isinstance(answer, BotMessage):
        payload: dict[str, Any] = {"content": answer.content}
        if answer.markdown or answer.keyboard:
            payload["msg_type"] = 2
            payload["markdown"] = answer.markdown or {"content": answer.content}
        if answer.keyboard:
            payload["keyboard"] = answer.keyboard
        return payload
    return {"content": answer}


def _extract_user_id(message: Any) -> str:
    author = getattr(message, "author", None)
    for value in (
        getattr(author, "id", None),
        getattr(author, "user_openid", None),
        getattr(author, "member_openid", None),
        getattr(message, "user_openid", None),
        getattr(message, "member_openid", None),
        getattr(message, "openid", None),
    ):
        if value:
            return str(value)
    return "unknown"


def _extract_mention_user_ids(message: Any) -> list[str]:
    result = []
    for mention in getattr(message, "mentions", []) or []:
        for value in (
            getattr(mention, "id", None),
            getattr(mention, "user_openid", None),
            getattr(mention, "member_openid", None),
            getattr(mention, "openid", None),
        ):
            if value:
                result.append(str(value))
                break
    return result


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
