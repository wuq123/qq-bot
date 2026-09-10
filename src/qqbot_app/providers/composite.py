from pathlib import Path
from typing import Any, Optional

from qqbot_app.auth_service import AuthCommand, AuthService, parse_auth_command
from qqbot_app.coc_service import CocCommand, CocService, parse_coc_command
from qqbot_app.note_service import NoteService, parse_note_command
from qqbot_app.providers.base import AnswerContext, AnswerProvider


class ChatAnswerProvider(AnswerProvider):
    def __init__(
        self,
        faq_provider: AnswerProvider,
        note_root: str,
        auth_service: AuthService,
        coc_api_token: str = "",
        coc_translations_path: str = "",
        coc_service: Optional[Any] = None,
    ) -> None:
        self._faq_provider = faq_provider
        self._note_service = NoteService(Path(note_root)) if note_root else None
        self._auth_service = auth_service
        self._coc_service = coc_service or CocService(coc_api_token, coc_translations_path)

    def answer(self, user_id: str, text: str, context: AnswerContext) -> str:
        auth_command = parse_auth_command(text)
        if auth_command is not None:
            return self._handle_auth_command(user_id, auth_command, context)

        coc_command = parse_coc_command(text)
        if coc_command is not None:
            return self._handle_coc_command(user_id, coc_command)

        command = parse_note_command(text)
        if command is None:
            return self._faq_provider.answer(user_id, text, context)

        if command.action == "invalid":
            return "笔记命令格式不正确。请发送：新增笔记 标题：Git 内容：这里是内容，或：查看笔记：Git。"
        if not self._auth_service.can_use(user_id, "notes"):
            return self._auth_service.feature_error(user_id, "笔记")
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


def _target_mention_user_id(actor_user_id: str, context: AnswerContext) -> str:
    mention_user_ids = [value for value in context.extra.get("mention_user_ids", []) if value and value != actor_user_id]
    if not mention_user_ids:
        return ""
    return mention_user_ids[-1]
