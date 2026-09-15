import re
from typing import Any, Optional

from qqbot_app.actions import BotActionService
from qqbot_app.auth_service import AuthService, parse_auth_command
from qqbot_app.coc_service import parse_coc_command
from qqbot_app.help_service import HelpService
from qqbot_app.note_service import parse_note_command
from qqbot_app.providers.base import AnswerContext, AnswerProvider, BotAnswer
from qqbot_app.wuwa_service import parse_wuwa_command


class ChatAnswerProvider(AnswerProvider):
    def __init__(
        self,
        faq_provider: AnswerProvider,
        note_root: str,
        auth_service: AuthService,
        help_service: Optional[HelpService] = None,
        coc_api_token: str = "",
        coc_translations_path: str = "",
        coc_service: Optional[Any] = None,
        wuwa_data_dir: str = "data/wuwa",
        wuwa_timeout: int = 10,
        wuwa_service: Optional[Any] = None,
        action_service: Optional[BotActionService] = None,
    ) -> None:
        self._faq_provider = faq_provider
        self._help_service = help_service
        self._actions = action_service or BotActionService(
            note_root=note_root,
            auth_service=auth_service,
            coc_api_token=coc_api_token,
            coc_translations_path=coc_translations_path,
            coc_service=coc_service,
            wuwa_data_dir=wuwa_data_dir,
            wuwa_timeout=wuwa_timeout,
            wuwa_service=wuwa_service,
        )

    def answer(self, user_id: str, text: str, context: AnswerContext) -> BotAnswer:
        auth_command = parse_auth_command(text)
        if auth_command is not None:
            return self._actions.handle_auth(user_id, auth_command, context)

        coc_command = parse_coc_command(text)
        if coc_command is not None:
            return self._actions.handle_coc(user_id, coc_command)

        wuwa_command = parse_wuwa_command(text)
        if wuwa_command is not None:
            return self._actions.handle_wuwa(user_id, wuwa_command, context)

        note_command = parse_note_command(text)
        if note_command is None:
            if looks_like_wuwa_credentials(text):
                return "鸣潮手机号、验证码和 Token 仅支持私聊固定格式：鸣潮登录：<手机号>、鸣潮验证码：<验证码>、绑定鸣潮Token：<Token>。"
            hidden_help_features = set() if context.event_type.startswith("onebot_") else {"blackjack"}
            help_answer = self._help_service.answer(text, hidden_help_features) if self._help_service else None
            if help_answer is not None:
                return help_answer
            return self._faq_provider.answer(user_id, text, context)
        return self._actions.handle_note(user_id, note_command)


def looks_like_wuwa_credentials(text: str) -> bool:
    value = str(text or "").lower()
    mentions_secret = any(keyword in value for keyword in ("手机号", "验证码", "token", "登录凭据"))
    related_action = any(keyword in value for keyword in ("鸣潮", "登录", "绑定"))
    mentions_mobile = bool(re.search(r"(?<!\d)1\d{10}(?!\d)", value))
    return (mentions_secret and related_action) or (mentions_mobile and "鸣潮" in value)
