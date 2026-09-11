import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import botpy
from dotenv import load_dotenv

from qqbot_app.auth_service import AuthService, FeatureNames
from qqbot_app.bot_client import QQQuestionAnswerBot
from qqbot_app.config import BotConfig
from qqbot_app.help_service import HelpService
from qqbot_app.providers import ChatAnswerProvider
from qqbot_app.qa_service import FaqAnswerProvider


def create_intents() -> botpy.Intents:
    """创建消息订阅 intents"""
    try:
        return botpy.Intents(public_guild_messages=True, public_messages=True, direct_message=True)
    except TypeError:
        return botpy.Intents.all()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s", force=True)
    load_dotenv()
    config = BotConfig.from_env()
    intents = create_intents()
    print(
        "bot debug: starting "
        f"sandbox={config.sandbox} "
        f"intents={intents.value} "
        f"public_messages={intents.public_messages} "
        f"public_guild_messages={intents.public_guild_messages} "
        f"direct_message={intents.direct_message}",
        flush=True,
    )
    faq_provider = FaqAnswerProvider.from_file(Path(config.faq_path))
    help_service = HelpService.from_file(Path(config.help_path))
    feature_names = FeatureNames.from_file(Path(config.feature_names_path))
    auth_service = AuthService(Path(config.auth_config_path), config.bot_owner_user_ids, feature_names)
    provider = ChatAnswerProvider(
        faq_provider=faq_provider,
        note_root=config.note_root,
        auth_service=auth_service,
        help_service=help_service,
        coc_api_token=config.coc_api_token,
        coc_translations_path=config.coc_translations_path,
        wuwa_data_dir=config.wuwa_data_dir,
        wuwa_timeout=config.wuwa_timeout,
    )
    client = QQQuestionAnswerBot(provider, intents=intents, is_sandbox=config.sandbox)
    client.run(appid=config.app_id, secret=config.app_secret)


if __name__ == "__main__":
    main()
