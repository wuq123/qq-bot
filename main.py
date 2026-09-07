import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import botpy
from dotenv import load_dotenv

from qqbot_app.bot_client import QQQuestionAnswerBot
from qqbot_app.config import BotConfig
from qqbot_app.qa_service import FaqAnswerProvider


def create_intents() -> botpy.Intents:
    """创建消息订阅 intents"""
    try:
        return botpy.Intents(public_guild_messages=True, public_messages=True)
    except TypeError:
        return botpy.Intents.all()


def main() -> None:
    load_dotenv()
    config = BotConfig.from_env()
    provider = FaqAnswerProvider.from_file(Path(config.faq_path))
    client = QQQuestionAnswerBot(provider, intents=create_intents(), is_sandbox=config.sandbox)
    client.run(appid=config.app_id, secret=config.app_secret)


if __name__ == "__main__":
    main()
