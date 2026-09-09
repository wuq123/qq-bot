import os
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class BotConfig:
    app_id: str
    app_secret: str
    sandbox: bool
    faq_path: str
    note_root: str
    auth_config_path: str
    bot_owner_user_ids: List[str]

    @classmethod
    def from_env(cls) -> "BotConfig":
        app_id = os.getenv("QQBOT_APP_ID", "").strip()
        app_secret = os.getenv("QQBOT_APP_SECRET", "").strip()
        sandbox = os.getenv("QQBOT_SANDBOX", "true").strip().lower() in {"1", "true", "yes", "on"}
        faq_path = os.getenv("QQBOT_FAQ_PATH", "config/faq.yaml").strip()
        note_root = os.getenv("NOTE_ROOT", "").strip()
        auth_config_path = os.getenv("AUTH_CONFIG_PATH", "config/auth.yaml").strip()
        bot_owner_user_ids = _parse_csv(os.getenv("BOT_OWNER_USER_IDS", ""))

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
            note_root=note_root,
            auth_config_path=auth_config_path,
            bot_owner_user_ids=bot_owner_user_ids,
        )


def _parse_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
