from pathlib import Path
from typing import Any, Optional

from qqbot_app.auth_service import AuthCommand, AuthService, parse_auth_command
from qqbot_app.coc_service import CocCommand, CocService, parse_coc_command
from qqbot_app.help_service import HelpService
from qqbot_app.note_service import NoteService, parse_note_command
from qqbot_app.providers.base import AnswerContext, AnswerProvider, BotAnswer
from qqbot_app.wuwa_service import WuwaCommand, WuwaService, parse_wuwa_command


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
    ) -> None:
        self._faq_provider = faq_provider
        self._note_service = NoteService(Path(note_root)) if note_root else None
        self._auth_service = auth_service
        self._help_service = help_service
        self._coc_service = coc_service or CocService(coc_api_token, coc_translations_path)
        self._wuwa_service = wuwa_service or WuwaService(wuwa_data_dir, wuwa_timeout)

    def answer(self, user_id: str, text: str, context: AnswerContext) -> BotAnswer:
        auth_command = parse_auth_command(text)
        if auth_command is not None:
            return self._handle_auth_command(user_id, auth_command, context)

        coc_command = parse_coc_command(text)
        if coc_command is not None:
            return self._handle_coc_command(user_id, coc_command)

        wuwa_command = parse_wuwa_command(text)
        if wuwa_command is not None:
            return self._handle_wuwa_command(user_id, wuwa_command, context)

        note_command = parse_note_command(text)
        if note_command is None:
            help_answer = self._help_service.answer(text) if self._help_service else None
            if help_answer is not None:
                return help_answer
            return self._faq_provider.answer(user_id, text, context)

        command = note_command
        if command.action == "invalid":
            return "笔记命令格式不正确。请发送：新增笔记 标题：Git 内容：这里是内容，或：查看笔记：Git。"
        if not self._auth_service.can_use(user_id, "notes"):
            return self._auth_service.feature_error(user_id, "笔记")
        if command.action in {"create", "append"} and not self._auth_service.has_at_least(
            user_id, "notes", "admin"
        ):
            return "新增或修改共享笔记需要笔记 admin 或 owner 权限。"
        if not self._note_service:
            return "未配置笔记目录 NOTE_ROOT，暂时无法管理笔记。"
        if command.action in {"create", "append"} and not command.content:
            return "笔记内容不能为空。"

        try:
            if command.action == "list":
                return self._note_service.list_notes()
            if command.action == "read":
                return self._note_service.read_note(command.title)
            if command.action == "create":
                return self._note_service.create_note(command.title, command.content)
            return self._note_service.append_note(command.title, command.content)
        except ValueError as exc:
            return str(exc)

    def _handle_auth_command(self, user_id: str, command: AuthCommand, context: AnswerContext) -> str:
        if command.action == "me":
            return f"当前用户ID：{user_id}"
        if command.action == "describe":
            target_user_id = command.target_user_id or user_id
            return self._auth_service.describe(target_user_id)
        if command.action == "grant":
            return self._auth_service.grant(user_id, command.target_user_id, command.feature, command.role)
        if command.action == "promote":
            if context.event_type != "group_at_message":
                return "提升权限只能在群聊中使用。"
            target_user_id = _target_mention_user_id(user_id, context)
            return self._auth_service.promote(user_id, target_user_id, command.feature)
        return "权限命令格式不正确。请发送：设置权限 用户：<user_id> 功能：笔记 身份：user，或：查看权限。"

    def _handle_coc_command(self, user_id: str, command: CocCommand) -> str:
        if command.action == "invalid":
            return "部落冲突命令格式不正确。请发送：查询玩家：#ABC123。"
        if not self._auth_service.can_use(user_id, "clash"):
            return self._auth_service.feature_error(user_id, "部落冲突查询")
        if command.action == "clan_war":
            return self._coc_service.get_clan_war_summary(command.player_tag)
        if command.action == "capital_raid":
            return self._coc_service.get_capital_raid_summary(command.player_tag)
        if command.action == "battlelog":
            return self._coc_service.get_player_battlelog_summary(command.player_tag)
        if command.action == "league_history":
            return self._coc_service.get_player_league_history_summary(command.player_tag)
        if command.action == "building_time":
            return self._coc_service.get_building_time_summary(command.player_tag)
        return self._coc_service.get_player_summary(command.player_tag)

    def _handle_wuwa_command(self, user_id: str, command: WuwaCommand, context: AnswerContext) -> BotAnswer:
        if command.action == "invalid":
            return "鸣潮命令格式不正确。请发送：鸣潮登录：<手机号>、鸣潮面板、练度：今汐，或：导入鸣潮抽卡：<唤取记录URL>。"
        if not self._auth_service.can_use(user_id, "wuwa"):
            return self._auth_service.feature_error(user_id, "鸣潮")
        if command.action in {"request_sms", "submit_sms", "bind_token"} and context.event_type not in {"c2c_message", "direct_message"}:
            return "鸣潮登录凭据只能在私聊中发送，请删除包含手机号、验证码或 Token 的公开消息。"
        if command.action == "request_sms":
            return self._wuwa_service.request_sms_code(user_id, command.value)
        if command.action == "submit_sms":
            return self._wuwa_service.submit_sms_code(user_id, command.value)
        if command.action == "bind_token":
            return self._wuwa_service.bind_token(user_id, command.value)
        if command.action == "bind_role":
            return self._wuwa_service.bind_role(user_id, command.value, command.server_id)
        if command.action == "describe_binding":
            return self._wuwa_service.describe_binding(user_id)
        if command.action == "delete_binding":
            return self._wuwa_service.delete_binding(user_id)
        if command.action == "profile":
            return self._wuwa_service.get_profile_summary(user_id)
        if command.action == "stamina":
            return self._wuwa_service.get_stamina_summary(user_id)
        if command.action == "character":
            return self._wuwa_service.get_character_summary(user_id, command.value)
        if command.action == "import_gacha_url":
            return self._wuwa_service.import_gacha_url(user_id, command.value)
        if command.action == "import_gacha_json":
            return self._wuwa_service.import_gacha_json(user_id, command.value)
        if command.action == "gacha_analysis":
            return self._wuwa_service.get_gacha_analysis(user_id, command.value)
        return "鸣潮命令格式不正确。"


def _target_mention_user_id(actor_user_id: str, context: AnswerContext) -> str:
    mention_user_ids = [value for value in context.extra.get("mention_user_ids", []) if value and value != actor_user_id]
    if not mention_user_ids:
        return ""
    return mention_user_ids[-1]
