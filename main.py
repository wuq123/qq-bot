import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import botpy
from dotenv import load_dotenv

from qqbot_app.actions import BotActionService
from qqbot_app.agent_tools import AgentToolRegistry
from qqbot_app.auth_service import AuthService, FeatureNames
from qqbot_app.bot_client import QQQuestionAnswerBot
from qqbot_app.config import BotConfig
from qqbot_app.help_service import HelpService
from qqbot_app.onebot_client import OneBotBotClient, OneBotConfig
from qqbot_app.providers import ChatAnswerProvider, LangChainAgentProvider, LLMConfig
from qqbot_app.qa_service import FaqAnswerProvider


logger = logging.getLogger(__name__)


def create_intents() -> botpy.Intents:
    """创建消息订阅 intents"""
    try:
        return botpy.Intents(public_guild_messages=True, public_messages=True, direct_message=True)
    except TypeError:
        return botpy.Intents.all()


def create_onebot_client(
    config: OneBotConfig,
    provider: ChatAnswerProvider,
    llm_provider: LangChainAgentProvider | None,
) -> OneBotBotClient | None:
    if not config.enabled:
        return None
    access_token = os.getenv(config.access_token_env, "").strip()
    if not access_token:
        logger.warning("OneBot access token environment variable is empty: %s", config.access_token_env)
        return None
    if llm_provider is None:
        logger.warning("OneBot random LLM replies are disabled because LLM is unavailable")
    return OneBotBotClient(
        config,
        access_token,
        provider,
        llm_provider or _NoGroupResponder(),
        state_changed=_log_onebot_state,
    )


class _NoGroupResponder:
    def answer_group(self, messages: list[str]) -> None:
        return None


def _log_onebot_state(mode: str) -> None:
    if mode == "napcat":
        logger.info("NapCat is the primary message entry")
    else:
        logger.warning("NapCat is unavailable; botpy remains the fallback entry")


async def run_clients(
    client: QQQuestionAnswerBot,
    onebot_client: OneBotBotClient,
    app_id: str,
    app_secret: str,
) -> None:
    async with client:
        tasks = [
            asyncio.create_task(client.start(appid=app_id, secret=app_secret)),
            asyncio.create_task(onebot_client.run()),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


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
    help_service = HelpService.from_file(Path(config.help_path))
    feature_names = FeatureNames.from_data(config.feature_names)
    auth_service = AuthService(Path(config.auth_config_path), config.bot_owner_user_ids, feature_names)
    actions = BotActionService(
        note_root=config.note_root,
        auth_service=auth_service,
        coc_api_token=config.coc_api_token,
        coc_translations_path=config.coc_translations_path,
        wuwa_data_dir=config.wuwa_data_dir,
        wuwa_timeout=config.wuwa_timeout,
    )
    llm_config = LLMConfig.from_data(config.llm)
    onebot_config = OneBotConfig.from_data(config.onebot)
    llm_provider = None
    if llm_config.enabled:
        api_key = os.getenv(llm_config.api_key_env, "").strip()
        if api_key:
            llm_provider = LangChainAgentProvider(
                llm_config,
                api_key,
                AgentToolRegistry(actions, help_service),
            )
        else:
            logger.warning("LLM is enabled but API key environment variable is empty: %s", llm_config.api_key_env)
    faq_provider = FaqAnswerProvider.from_file(Path(config.faq_path), fallback_provider=llm_provider)
    provider = ChatAnswerProvider(
        faq_provider=faq_provider,
        note_root=config.note_root,
        auth_service=auth_service,
        help_service=help_service,
        coc_api_token=config.coc_api_token,
        coc_translations_path=config.coc_translations_path,
        wuwa_data_dir=config.wuwa_data_dir,
        wuwa_timeout=config.wuwa_timeout,
        action_service=actions,
    )
    client = QQQuestionAnswerBot(provider, intents=intents, is_sandbox=config.sandbox)
    onebot_client = create_onebot_client(onebot_config, provider, llm_provider)
    if onebot_client is None:
        client.run(appid=config.app_id, secret=config.app_secret)
    else:
        asyncio.run(run_clients(client, onebot_client, config.app_id, config.app_secret))


if __name__ == "__main__":
    main()
