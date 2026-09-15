from pathlib import Path

import pytest

from qqbot_app.config import BotConfig


def _write_app_config(tmp_path: Path) -> Path:
    path = tmp_path / "app.yaml"
    path.write_text(
        """bot:
  sandbox: false
paths:
  faq: config/custom.yaml
  help: config/custom-help.yaml
  note_root: C:\\notes
  auth: config/custom-auth.yaml
  coc_translations: config/custom-coc.yaml
  wuwa_data_dir: data/custom-wuwa
  wuwa_timeout: 15
features:
  notes: 笔记
llm:
  enabled: false
onebot:
  enabled: false
""",
        encoding="utf-8",
    )
    return path


def test_load_config_from_env_and_app_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("QQBOT_APP_ID", "app-id")
    monkeypatch.setenv("QQBOT_APP_SECRET", "secret")
    monkeypatch.setenv("APP_CONFIG_PATH", str(_write_app_config(tmp_path)))
    monkeypatch.setenv("BOT_OWNER_USER_IDS", "u1, u2, ,u3")
    monkeypatch.setenv("COC_API_TOKEN", "coc-token")

    config = BotConfig.from_env()

    assert config.app_id == "app-id"
    assert config.app_secret == "secret"
    assert config.sandbox is False
    assert config.faq_path == "config/custom.yaml"
    assert config.help_path == "config/custom-help.yaml"
    assert config.note_root == "C:\\notes"
    assert config.auth_config_path == "config/custom-auth.yaml"
    assert config.bot_owner_user_ids == ["u1", "u2", "u3"]
    assert config.feature_names == {"notes": "笔记"}
    assert config.coc_api_token == "coc-token"
    assert config.coc_translations_path == "config/custom-coc.yaml"
    assert config.wuwa_data_dir == "data/custom-wuwa"
    assert config.wuwa_timeout == 15
    assert config.llm == {"enabled": False}
    assert config.onebot == {"enabled": False}


def test_empty_bot_owner_user_ids(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("QQBOT_APP_ID", "app-id")
    monkeypatch.setenv("QQBOT_APP_SECRET", "secret")
    monkeypatch.setenv("APP_CONFIG_PATH", str(_write_app_config(tmp_path)))
    monkeypatch.delenv("BOT_OWNER_USER_IDS", raising=False)

    config = BotConfig.from_env()

    assert config.bot_owner_user_ids == []
    assert config.llm == {"enabled": False}
    assert config.onebot == {"enabled": False}


def test_missing_credentials_have_clear_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", str(_write_app_config(tmp_path)))
    monkeypatch.delenv("QQBOT_APP_ID", raising=False)
    monkeypatch.delenv("QQBOT_APP_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="QQBOT_APP_ID, QQBOT_APP_SECRET"):
        BotConfig.from_env()


def test_invalid_app_config_has_clear_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "app.yaml"
    path.write_text("paths: []", encoding="utf-8")
    monkeypatch.setenv("QQBOT_APP_ID", "app-id")
    monkeypatch.setenv("QQBOT_APP_SECRET", "secret")
    monkeypatch.setenv("APP_CONFIG_PATH", str(path))

    with pytest.raises(ValueError, match="paths"):
        BotConfig.from_env()
