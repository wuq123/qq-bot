import asyncio
import json
from pathlib import Path
import threading
from typing import Optional

import pytest
import yaml

from qqbot_app.bot_message import BotMessage
from qqbot_app.blackjack_service import BlackjackService
from qqbot_app.onebot_client import OneBotBotClient, OneBotConfig, OneBotGroupChatClient


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


class _Provider:
    def __init__(self, result: object = "业务回复") -> None:
        self.result = result
        self.calls: list[tuple[str, str, object]] = []

    def answer(self, user_id: str, text: str, context: object) -> object:
        self.calls.append((user_id, text, context))
        return self.result


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


def test_app_onebot_config_is_loaded() -> None:
    app_config = yaml.safe_load(Path("config/app.yaml").read_text(encoding="utf-8"))
    config = OneBotConfig.from_data(app_config["onebot"])

    assert config.enabled is True
    assert config.reply_probability == 0.02
    assert config.context_messages == 5
    assert config.reply_cooldown_seconds == 30
    assert config.max_reply_chars == 200


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
        ("enabled: false\nreply_cooldown_seconds: 0", "reply_cooldown_seconds"),
        ("enabled: false\nmax_reply_chars: 0", "max_reply_chars"),
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


@pytest.mark.parametrize(
    ("messages", "answer"),
    [(["第一条"], "第一条"), (["第一条", "第二条"], "第一条\n第二条"), (["第一条"], "x" * 201)],
)
def test_context_echo_or_oversized_answer_is_not_sent(messages: list[str], answer: str) -> None:
    responder = _Responder(answer=answer)
    random_values = iter([1.0] * (len(messages) - 1) + [0.0])
    client = OneBotGroupChatClient(
        _config(max_reply_chars=200),
        "token",
        responder,
        random_value=lambda: next(random_values),
    )

    async def run() -> list[str]:
        sent: list[str] = []

        async def send(value: str) -> None:
            sent.append(value)

        for message in messages:
            await client.handle_event(_event(message), send)
        return sent

    assert asyncio.run(run()) == []


def test_duplicate_message_and_cooldown_do_not_call_llm_twice() -> None:
    responder = _Responder()
    now = [0.0]
    client = OneBotGroupChatClient(
        _config(reply_cooldown_seconds=30),
        "token",
        responder,
        random_value=lambda: 0.0,
        clock=lambda: now[0],
    )

    first = asyncio.run(_handle(client, _event("第一条", message_id=1)))
    duplicate = asyncio.run(_handle(client, _event("第一条", message_id=1)))
    now[0] = 10
    during_cooldown = asyncio.run(_handle(client, _event("第二条", message_id=2)))
    now[0] = 30
    after_cooldown = asyncio.run(_handle(client, _event("第三条", message_id=3)))

    assert len(first) == 1
    assert duplicate == []
    assert during_cooldown == []
    assert len(after_cooldown) == 1
    assert responder.calls == [["第一条"], ["第一条", "第二条", "第三条"]]


def test_reply_in_progress_blocks_another_group_llm_call() -> None:
    class _BlockingResponder(_Responder):
        def __init__(self) -> None:
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()

        def answer_group(self, messages: list[str]) -> Optional[str]:
            self.calls.append(messages)
            self.started.set()
            assert self.release.wait(timeout=1)
            return self.answer

    responder = _BlockingResponder()
    client = OneBotGroupChatClient(_config(), "token", responder, random_value=lambda: 0.0)

    async def run() -> list[str]:
        sent: list[str] = []

        async def send(value: str) -> None:
            sent.append(value)

        first = asyncio.create_task(client.handle_event(_event("第一条"), send))
        assert await asyncio.to_thread(responder.started.wait, 1)
        await client.handle_event(_event("第二条"), send)
        responder.release.set()
        await first
        return sent

    assert len(asyncio.run(run())) == 1
    assert responder.calls == [["第一条"]]


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


def test_full_client_routes_private_and_group_at_but_ignores_other_mentions() -> None:
    provider = _Provider()
    client = OneBotBotClient(_config(), "token", provider, _Responder(), random_value=lambda: 1.0)

    private = asyncio.run(_handle(client, _event("私聊", message_type="private", user_id=201)))
    group_at = asyncio.run(
        _handle(client, _event([{"type": "at", "data": {"qq": "999"}}, {"type": "text", "data": {"text": "群命令"}}]))
    )
    foreign_at = asyncio.run(
        _handle(client, _event([{"type": "at", "data": {"qq": "888"}}, {"type": "text", "data": {"text": "官方入口"}}]))
    )

    assert len(private) == 1
    assert len(group_at) == 1
    assert foreign_at == []
    assert [call[:2] for call in provider.calls] == [("201", "私聊"), ("200", "群命令")]
    assert provider.calls[1][2].extra == {"conversation_id": "group:100", "mention_user_ids": ["999"]}


def test_full_client_sends_image_and_drops_markdown_keyboard() -> None:
    provider = _Provider(BotMessage(content="帮助", markdown={"content": "富消息"}, keyboard={"content": {}}, image=b"png"))
    client = OneBotBotClient(_config(), "token", provider, _Responder(), random_value=lambda: 1.0)

    sent = asyncio.run(_handle(client, _event("图片", message_type="private")))

    request = json.loads(sent[0])
    assert request["action"] == "send_private_msg"
    assert request["params"]["message"][0] == {"type": "text", "data": {"text": "帮助"}}
    assert request["params"]["message"][1]["type"] == "image"
    assert "keyboard" not in str(request)


def test_blackjack_is_handled_only_by_onebot_business_messages() -> None:
    provider = _Provider()
    blackjack = BlackjackService(deck_factory=lambda: ["7", "10", "K", "A"])
    client = OneBotBotClient(_config(), "token", provider, _Responder(), blackjack_service=blackjack)

    private = asyncio.run(_handle(client, _event("21点", message_type="private", user_id=201)))
    group_at = asyncio.run(
        _handle(client, _event([{"type": "at", "data": {"qq": "999"}}, {"type": "text", "data": {"text": "21点"}}]))
    )

    assert len(private) == 1
    assert len(group_at) == 1
    assert provider.calls == []
    assert "Blackjack" in private[0]
    assert "Blackjack" in group_at[0]


def test_active_group_blackjack_accepts_unmentioned_actions() -> None:
    provider = _Provider()
    blackjack = BlackjackService(deck_factory=lambda: ["K", "7", "9", "6", "10"])
    client = OneBotBotClient(_config(), "token", provider, _Responder(), random_value=lambda: 1.0, blackjack_service=blackjack)

    started = asyncio.run(
        _handle(client, _event([{"type": "at", "data": {"qq": "999"}}, {"type": "text", "data": {"text": "21点"}}]))
    )
    hit = asyncio.run(_handle(client, _event("要牌")))

    assert len(started) == 1
    assert len(hit) == 1
    assert "你爆牌了。" in hit[0]
    assert provider.calls == []


def test_blackjack_dealer_draws_are_sent_as_separate_messages() -> None:
    blackjack = BlackjackService(deck_factory=lambda: ["K", "6", "5", "7", "10"])
    client = OneBotBotClient(_config(), "token", _Provider(), _Responder(), blackjack_service=blackjack)

    asyncio.run(
        _handle(client, _event([{"type": "at", "data": {"qq": "999"}}, {"type": "text", "data": {"text": "21点"}}]))
    )
    replies = asyncio.run(_handle(client, _event("停牌")))

    assert len(replies) == 3
    assert "庄家翻开暗牌：5、6（11 点）" in replies[0]
    assert "庄家要牌：K（21 点）" in replies[1]
    assert "庄家的牌：5、6、K（21 点）" in replies[2]


def test_full_client_reaches_fallback_state_after_reconnect_failures() -> None:
    modes: list[str] = []

    def connect(*args: object, **kwargs: object) -> object:
        raise RuntimeError("offline")

    sleeps = [0]

    async def sleep(_: float) -> None:
        sleeps[0] += 1
        if sleeps[0] >= 3:
            raise asyncio.CancelledError

    client = OneBotBotClient(_config(failover_after_failures=3), "token", _Provider(), _Responder(), connect=connect, sleep=sleep, state_changed=modes.append)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(client.run())

    assert modes == ["botpy_fallback"]
