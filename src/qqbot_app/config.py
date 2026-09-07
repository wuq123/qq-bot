import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BotConfig:
    app_id: str
    app_secret: str
    sandbox: bool
    faq_path: str

    @classmethod
    def from_env(cls) -> "BotConfig":
        app_id = os.getenv("QQBOT_APP_ID", "").strip()
        app_secret = os.getenv("QQBOT_APP_SECRET", "").strip()
        sandbox = os.getenv("QQBOT_SANDBOX", "true").strip().lower() in {"1", "true", "yes", "on"}
        faq_path = os.getenv("QQBOT_FAQ_PATH", "config/faq.yaml").strip()

        missing = []
        if not app_id:
            missing.append("QQBOT_APP_ID")
        if not app_secret:
            missing.append("QQBOT_APP_SECRET")
        if missing:
            raise RuntimeError(f"缺少必要环境变量: {', '.join(missing)}")

        return cls(app_id=app_id, app_secret=app_secret, sandbox=sandbox, faq_path=faq_path)
