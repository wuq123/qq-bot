from pathlib import Path
from typing import Iterable, Set

from qqbot_app.note_service import NoteService, parse_note_command
from qqbot_app.providers.base import AnswerContext, AnswerProvider


class ChatAnswerProvider(AnswerProvider):
    def __init__(self, faq_provider: AnswerProvider, note_root: str, note_allowed_user_ids: Iterable[str] = ()) -> None:
        self._faq_provider = faq_provider
        self._note_service = NoteService(Path(note_root)) if note_root else None
        self._note_allowed_user_ids: Set[str] = {user_id.strip() for user_id in note_allowed_user_ids if user_id.strip()}

    def answer(self, user_id: str, text: str, context: AnswerContext) -> str:
        command = parse_note_command(text)
        if command is None:
            return self._faq_provider.answer(user_id, text, context)

        auth_error = self._check_note_permission(user_id)
        if auth_error:
            return auth_error
        if command.action == "invalid":
            return "笔记命令格式不正确。请发送：新增笔记 标题：Git 内容：这里是内容，或：查看笔记：Git。"
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

    def _check_note_permission(self, user_id: str) -> str:
        if user_id == "unknown":
            return "无法识别用户身份，已拒绝笔记操作。"
        if not self._note_allowed_user_ids:
            return "未配置 NOTE_ALLOWED_USER_IDS，已拒绝笔记操作。"
        if user_id not in self._note_allowed_user_ids:
            return "你没有权限操作笔记。"
        return ""
