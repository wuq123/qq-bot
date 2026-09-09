from pathlib import Path

from qqbot_app.auth_service import AuthCommand, AuthService, parse_auth_command
from qqbot_app.note_service import NoteService, parse_note_command
from qqbot_app.providers.base import AnswerContext, AnswerProvider


class ChatAnswerProvider(AnswerProvider):
    def __init__(self, faq_provider: AnswerProvider, note_root: str, auth_service: AuthService) -> None:
        self._faq_provider = faq_provider
        self._note_service = NoteService(Path(note_root)) if note_root else None
        self._auth_service = auth_service

    def answer(self, user_id: str, text: str, context: AnswerContext) -> str:
        auth_command = parse_auth_command(text)
        if auth_command is not None:
            return self._handle_auth_command(user_id, auth_command)

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

    def _handle_auth_command(self, user_id: str, command: AuthCommand) -> str:
        if command.action == "me":
            return f"当前用户ID：{user_id}"
        if command.action == "describe":
            target_user_id = command.target_user_id or user_id
            return self._auth_service.describe(target_user_id)
        if command.action == "grant":
            return self._auth_service.grant(user_id, command.target_user_id, command.feature, command.role)
        return "权限命令格式不正确。请发送：设置权限 用户：<user_id> 功能：notes 身份：user，或：查看权限。"
