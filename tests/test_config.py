import pytest

from qqbot_app.config import BotConfig


def test_load_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QQBOT_APP_ID", "app-id")
    monkeypatch.setenv("QQBOT_APP_SECRET", "secret")
    monkeypatch.setenv("QQBOT_SANDBOX", "false")
    monkeypatch.setenv("QQBOT_FAQ_PATH", "config/custom.yaml")
    monkeypatch.setenv("NOTE_ROOT", "C:\\notes")
    monkeypatch.setenv("AUTH_CONFIG_PATH", "config/custom-auth.yaml")
    monkeypatch.setenv("BOT_OWNER_USER_IDS", "u1, u2, ,u3")

    config = BotConfig.from_env()

    assert config.app_id == "app-id"
    assert config.app_secret == "secret"
    assert config.sandbox is False
    assert config.faq_path == "config/custom.yaml"
    assert config.note_root == "C:\\notes"
    assert config.auth_config_path == "config/custom-auth.yaml"
    assert config.bot_owner_user_ids == ["u1", "u2", "u3"]


def test_empty_bot_owner_user_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QQBOT_APP_ID", "app-id")
    monkeypatch.setenv("QQBOT_APP_SECRET", "secret")
    monkeypatch.delenv("BOT_OWNER_USER_IDS", raising=False)

    config = BotConfig.from_env()

    assert config.bot_owner_user_ids == []


def test_missing_credentials_have_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QQBOT_APP_ID", raising=False)
    monkeypatch.delenv("QQBOT_APP_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="QQBOT_APP_ID, QQBOT_APP_SECRET"):
        BotConfig.from_env()
