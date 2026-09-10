import asyncio
from types import SimpleNamespace

from qqbot_app.bot_client import QQQuestionAnswerBot, _build_payload, _extract_mention_user_ids, _extract_user_id, _send_reply
from qqbot_app.providers import BotMessage


class _ReplyMessage:
    def __init__(self, fail_once: bool = False) -> None:
        self.calls = []
        self._fail_once = fail_once

    async def reply(self, **kwargs: object) -> None:
        self.calls.append(kwargs)
        if self._fail_once:
            self._fail_once = False
            raise RuntimeError("rich failed")


def test_extract_user_id_from_channel_author_id() -> None:
    message = SimpleNamespace(author=SimpleNamespace(id="channel-user"))

    assert _extract_user_id(message) == "channel-user"


def test_extract_user_id_from_c2c_user_openid() -> None:
    message = SimpleNamespace(author=SimpleNamespace(user_openid="c2c-openid"))

    assert _extract_user_id(message) == "c2c-openid"


def test_extract_user_id_from_group_member_openid() -> None:
    message = SimpleNamespace(author=SimpleNamespace(member_openid="group-member-openid"))

    assert _extract_user_id(message) == "group-member-openid"


def test_extract_user_id_unknown() -> None:
    message = SimpleNamespace(author=SimpleNamespace())

    assert _extract_user_id(message) == "unknown"


def test_extract_mention_user_ids() -> None:
    message = SimpleNamespace(
        mentions=[
            SimpleNamespace(id="channel-user"),
            SimpleNamespace(member_openid="group-user"),
            SimpleNamespace(user_openid="c2c-user"),
        ]
    )

    assert _extract_mention_user_ids(message) == ["channel-user", "group-user", "c2c-user"]


def test_build_payload_for_rich_message() -> None:
    answer = BotMessage(
        content="帮助",
        markdown={"content": "帮助"},
        keyboard={"content": {"rows": []}},
    )

    payload = _build_payload(answer)

    assert payload["msg_type"] == 2
    assert payload["markdown"] == {"content": "帮助"}
    assert payload["keyboard"] == {"content": {"rows": []}}


def test_send_reply_falls_back_when_rich_message_fails() -> None:
    message = _ReplyMessage(fail_once=True)
    answer = BotMessage(content="纯文本帮助", markdown={"content": "富帮助"}, keyboard={"content": {"rows": []}})

    asyncio.run(_send_reply(message, "group_at_message", answer))

    assert message.calls == [
        {"content": "纯文本帮助", "msg_type": 2, "markdown": {"content": "富帮助"}, "keyboard": {"content": {"rows": []}}},
        {"content": "纯文本帮助"},
    ]


def test_send_reply_removes_msg_type_for_channel_reply() -> None:
    message = _ReplyMessage()
    answer = BotMessage(content="帮助", markdown={"content": "帮助"}, keyboard={"content": {"rows": []}})

    asyncio.run(_send_reply(message, "at_message", answer))

    assert message.calls == [{"content": "帮助", "markdown": {"content": "帮助"}, "keyboard": {"content": {"rows": []}}}]


def test_send_reply_keeps_plain_text_behavior() -> None:
    message = _ReplyMessage()

    asyncio.run(_send_reply(message, "group_at_message", "普通回答"))

    assert message.calls == [{"content": "普通回答"}]


def test_group_manage_event_handlers_do_not_fail() -> None:
    bot = object.__new__(QQQuestionAnswerBot)
    event = SimpleNamespace(group_openid="group-1")

    asyncio.run(bot.on_group_add_robot(event))
    asyncio.run(bot.on_group_msg_receive(event))
    asyncio.run(bot.on_group_msg_reject(event))
