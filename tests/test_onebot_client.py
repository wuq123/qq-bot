import asyncio
import json
from pathlib import Path
from typing import Optional

import pytest

from qqbot_app.onebot_client import OneBotConfig, OneBotGroupChatClient


class _Responder:
    def __init__(self, answer: Optional[str] = "群聊回答", error: bool = False) -> None:
        self.answer = answer
        self.error = error
        self.calls: list[list[str]] = []

    def answer_group(self, messages: list[str]) -> Optional[str]:
        self.calls.append(messages)
        if self.error:
            raise RuntimeError("failed")
        return self.answer


def _config(**overrides: object) -> OneBotConfig:
    values = {
        "enabled": True,
        "ws_url": "ws://127.0.0.1:3001",
        "access_token_env": "ONEBOT_ACCESS_TOKEN",
        "reply_probability": 0.2,
        "context_messages": 5,
        "max_message_chars": 500,
        "reconnect_delay": 5.0,
    }
    values.update(overrides)
    return OneBotConfig(**values)


def _event(text: object, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 100,
        "user_id": 200,
        "self_id": 999,
        "message": text,
    }
    value.update(overrides)
    return value


async def _handle(client: OneBotGroupChatClient, event: dict[str, object]) -> list[str]:
    sent: list[str] = []

    async def send(value: str) -> None:
        sent.append(value)

    await client.handle_event(event, send)
    return sent


def test_load_onebot_config(tmp_path: Path) -> None:
    path = tmp_path / "onebot.yaml"
    path.write_text(
        """enabled: true
ws_url: wss://onebot.example/ws
access_token_env: CUSTOM_ONEBOT_TOKEN
reply_probability: 0.25
context_messages: 4
max_message_chars: 300
reconnect_delay: 2.5
""",
        encoding="utf-8",
    )

    assert OneBotConfig.from_file(path) == OneBotConfig(
        True,
        "wss://onebot.example/ws",
        "CUSTOM_ONEBOT_TOKEN",
        0.25,
        4,
        300,
        2.5,
    )


def test_default_onebot_config_is_disabled() -> None:
    config = OneBotConfig.from_file(Path("config/onebot.yaml"))

    assert config.enabled is False
    assert config.reply_probability == 0.2
    assert config.context_messages == 5


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ('enabled: "yes"', "enabled"),
        ("enabled: true\nws_url: http://localhost", "ws_url"),
        ("enabled: true\naccess_token_env: ''", "access_token_env"),
        ("enabled: false\nreply_probability: 1.1", "reply_probability"),
        ("enabled: false\ncontext_messages: 0", "context_messages"),
        ("enabled: false\nmax_message_chars: 0", "max_message_chars"),
        ("enabled: false\nreconnect_delay: 0", "reconnect_delay"),
    ],
)
def test_invalid_onebot_config_has_clear_error(tmp_path: Path, content: str, error: str) -> None:
    path = tmp_path / "onebot.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        OneBotConfig.from_file(path)


def test_probability_boundary_and_plain_send_payload() -> None:
    responder = _Responder()
    values = iter([0.19, 0.2])
    client = OneBotGroupChatClient(_config(), "token", responder, random_value=lambda: next(values))

    first = asyncio.run(_handle(client, _event("第一条")))
    second = asyncio.run(_handle(client, _event("第二条")))

    assert len(first) == 1
    assert second == []
    assert responder.calls == [["第一条"]]
    request = json.loads(first[0])
    assert request == {
        "action": "send_group_msg",
        "params": {"group_id": 100, "message": [{"type": "text", "data": {"text": "群聊回答"}}]},
    }


def test_unsampled_messages_build_isolated_trimmed_group_context() -> None:
    responder = _Responder()
    values = iter([1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0])
    client = OneBotGroupChatClient(
        _config(context_messages=5, max_message_chars=4),
        "token",
        responder,
        random_value=lambda: next(values),
    )

    for index in range(1, 7):
        asyncio.run(_handle(client, _event(f"消息{index}超长")))
    asyncio.run(_handle(client, _event("另一群", group_id=101)))

    assert responder.calls[0] == ["消息2超", "消息3超", "消息4超", "消息5超", "消息6超"]
    assert responder.calls[1] == ["另一群"]


@pytest.mark.parametrize(
    "event",
    [
        _event("私聊", message_type="private"),
        _event("自己消息", user_id=999),
        _event("[CQ:at,qq=999] 你好"),
        _event([{"type": "at", "data": {"qq": "999"}}, {"type": "text", "data": {"text": "你好"}}]),
        _event([{"type": "image", "data": {"file": "a.png"}}]),
        _event("   "),
    ],
)
def test_non_ambient_group_messages_are_ignored(event: dict[str, object]) -> None:
    responder = _Responder()
    client = OneBotGroupChatClient(_config(), "token", responder, random_value=lambda: 0.0)

    assert asyncio.run(_handle(client, event)) == []
    assert responder.calls == []


def test_sensitive_message_is_not_stored_or_sent_to_llm() -> None:
    responder = _Responder()
    client = OneBotGroupChatClient(_config(), "token", responder, random_value=lambda: 0.0)

    assert asyncio.run(_handle(client, _event("请用手机号 13800138000 登录鸣潮"))) == []
    asyncio.run(_handle(client, _event("普通消息")))

    assert responder.calls == [["普通消息"]]


@pytest.mark.parametrize("answer,error", [(None, False), ("群聊回答", True)])
def test_llm_failure_or_empty_answer_is_not_sent(answer: Optional[str], error: bool) -> None:
    client = OneBotGroupChatClient(
        _config(),
        "token",
        _Responder(answer=answer, error=error),
        random_value=lambda: 0.0,
    )

    assert asyncio.run(_handle(client, _event("普通消息"))) == []


def test_send_failure_is_silently_ignored() -> None:
    client = OneBotGroupChatClient(_config(), "token", _Responder(), random_value=lambda: 0.0)

    async def run() -> None:
        async def send(_: str) -> None:
            raise RuntimeError("send failed")

        await client.handle_event(_event("普通消息"), send)

    asyncio.run(run())


def test_run_uses_bearer_header_and_reconnect_delay() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    delays: list[float] = []

    class _Socket:
        async def __aenter__(self) -> "_Socket":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def __aiter__(self) -> "_Socket":
            return self

        async def __anext__(self) -> str:
            raise StopAsyncIteration

        async def send(self, _: str) -> None:
            return None

    def connect(url: str, **kwargs: object) -> _Socket:
        calls.append((url, kwargs))
        return _Socket()

    async def sleep(delay: float) -> None:
        delays.append(delay)
        raise asyncio.CancelledError

    client = OneBotGroupChatClient(_config(), "secret", _Responder(), connect=connect, sleep=sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(client.run())

    assert calls == [("ws://127.0.0.1:3001", {"additional_headers": {"Authorization": "Bearer secret"}})]
    assert delays == [5.0]
