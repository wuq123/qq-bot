import logging

import pytest

import main
from qqbot_app.onebot_client import OneBotBotClient, OneBotConfig


def _config(enabled: bool = True) -> OneBotConfig:
    return OneBotConfig(enabled, "ws://127.0.0.1:3001", "ONEBOT_TOKEN", 0.2, 5, 500, 5)


def test_disabled_onebot_does_not_require_llm_or_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONEBOT_TOKEN", raising=False)

    assert main.create_onebot_client(_config(enabled=False), object(), None) is None


def test_enabled_onebot_without_llm_keeps_business_routes(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("ONEBOT_TOKEN", "token")
    with caplog.at_level(logging.WARNING):
        result = main.create_onebot_client(_config(), object(), None)

    assert isinstance(result, OneBotBotClient)
    assert "LLM is unavailable" in caplog.text


def test_enabled_onebot_without_token_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("ONEBOT_TOKEN", raising=False)

    with caplog.at_level(logging.WARNING):
        result = main.create_onebot_client(_config(), object(), object())

    assert result is None
    assert "ONEBOT_TOKEN" in caplog.text


def test_enabled_onebot_builds_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEBOT_TOKEN", "secret")

    result = main.create_onebot_client(_config(), object(), object())

    assert isinstance(result, OneBotBotClient)
