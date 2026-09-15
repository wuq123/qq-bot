import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml


@dataclass(frozen=True)
class BotConfig:
    app_id: str
    app_secret: str
    sandbox: bool
    faq_path: str
    help_path: str
    note_root: str
    auth_config_path: str
    bot_owner_user_ids: List[str]
    coc_api_token: str
    coc_translations_path: str
    wuwa_data_dir: str
    wuwa_timeout: int
    feature_names: Dict[str, str]
    llm: Dict[str, Any]
    onebot: Dict[str, Any]

    @classmethod
    def from_env(cls) -> "BotConfig":
        app_id = os.getenv("QQBOT_APP_ID", "").strip()
        app_secret = os.getenv("QQBOT_APP_SECRET", "").strip()
        data = _load_app_config(Path(os.getenv("APP_CONFIG_PATH", "config/app.yaml").strip()))
        bot = _section(data, "bot")
        paths = _section(data, "paths")
        sandbox = _read_bool(bot, "sandbox", True)
        faq_path = _read_text(paths, "faq", "config/faq.yaml")
        help_path = _read_text(paths, "help", "config/help.yaml")
        note_root = _read_text(paths, "note_root", "")
        auth_config_path = _read_text(paths, "auth", "config/auth.yaml")
        bot_owner_user_ids = _parse_csv(os.getenv("BOT_OWNER_USER_IDS", ""))
        coc_api_token = os.getenv("COC_API_TOKEN", "").strip()
        coc_translations_path = _read_text(paths, "coc_translations", "config/coc_translations.yaml")
        wuwa_data_dir = _read_text(paths, "wuwa_data_dir", "data/wuwa")
        wuwa_timeout = _read_positive_int(paths, "wuwa_timeout", 10)

        missing = []
        if not app_id:
            missing.append("QQBOT_APP_ID")
        if not app_secret:
            missing.append("QQBOT_APP_SECRET")
        if missing:
            raise RuntimeError(f"缺少必要环境变量: {', '.join(missing)}")

        return cls(
            app_id=app_id,
            app_secret=app_secret,
            sandbox=sandbox,
            faq_path=faq_path,
            help_path=help_path,
            note_root=note_root,
            auth_config_path=auth_config_path,
            bot_owner_user_ids=bot_owner_user_ids,
            coc_api_token=coc_api_token,
            coc_translations_path=coc_translations_path,
            wuwa_data_dir=wuwa_data_dir,
            wuwa_timeout=wuwa_timeout,
            feature_names={str(key): str(value) for key, value in _section(data, "features").items()},
            llm=_section(data, "llm"),
            onebot=_section(data, "onebot"),
        )


def _parse_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _load_app_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"应用配置文件不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("应用配置必须是 YAML 对象。")
    return data


def _section(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"应用配置 {name} 必须是 YAML 对象。")
    return value


def _read_text(data: Dict[str, Any], name: str, default: str) -> str:
    value = str(data.get(name, default)).strip()
    if not value and default:
        raise ValueError(f"应用配置 paths.{name} 不能为空。")
    return value


def _read_bool(data: Dict[str, Any], name: str, default: bool) -> bool:
    value = data.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"应用配置 bot.{name} 必须是布尔值。")
    return value


def _read_positive_int(data: Dict[str, Any], name: str, default: int) -> int:
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"应用配置 paths.{name} 必须是大于 0 的整数。")
    return value
