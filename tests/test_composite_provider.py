from pathlib import Path

from qqbot_app.auth_service import AuthService
from qqbot_app.providers import AnswerContext, ChatAnswerProvider
from qqbot_app.qa_service import FaqAnswerProvider, FaqItem


def _faq_provider() -> FaqAnswerProvider:
    return FaqAnswerProvider(
        fallback_answer="兜底回答",
        empty_answer="空消息回答",
        help_answer="帮助回答",
        items=[FaqItem(question="你能做什么", keywords=["功能"], answer="功能回答")],
    )


def _context() -> AnswerContext:
    return AnswerContext(event_type="test")


def _provider(tmp_path: Path) -> ChatAnswerProvider:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    auth_service.grant("owner-1", "u1", "notes", "user")
    return ChatAnswerProvider(faq_provider=_faq_provider(), note_root=str(tmp_path), auth_service=auth_service)


def _provider_with_auth(tmp_path: Path, auth_service: AuthService) -> ChatAnswerProvider:
    return ChatAnswerProvider(faq_provider=_faq_provider(), note_root=str(tmp_path), auth_service=auth_service)


def test_note_command_has_priority(tmp_path: Path) -> None:
    provider = _provider(tmp_path)

    answer = provider.answer("u1", "新增笔记 标题：功能 内容：笔记内容", _context())

    assert answer == "已新增笔记：功能.md"
    assert (tmp_path / "功能.md").exists()


def test_non_note_message_falls_back_to_faq(tmp_path: Path) -> None:
    provider = _provider_with_auth(tmp_path, AuthService(tmp_path / "auth.yaml"))

    answer = provider.answer("u1", "你能做什么", _context())

    assert answer == "功能回答"


def test_invalid_note_command_returns_format_tip(tmp_path: Path) -> None:
    provider = _provider(tmp_path)

    answer = provider.answer("u1", "新增笔记 Git 内容", _context())

    assert "笔记命令格式不正确" in answer


def test_note_command_without_root_returns_config_tip(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["u1"])
    provider = ChatAnswerProvider(faq_provider=_faq_provider(), note_root="", auth_service=auth_service)

    answer = provider.answer("u1", "新增笔记 标题：Git 内容：内容", _context())

    assert "未配置笔记目录 NOTE_ROOT" in answer


def test_list_note_command(tmp_path: Path) -> None:
    (tmp_path / "Git.md").write_text("Git 内容", encoding="utf-8")
    provider = _provider(tmp_path)

    answer = provider.answer("u1", "笔记列表", _context())

    assert answer == "现有笔记：\n- Git"


def test_read_note_command(tmp_path: Path) -> None:
    (tmp_path / "Git.md").write_text("Git 内容", encoding="utf-8")
    provider = _provider(tmp_path)

    answer = provider.answer("u1", "查看笔记：Git", _context())

    assert answer == "Git.md：\nGit 内容"


def test_append_note_command_allowed_for_notes_user(tmp_path: Path) -> None:
    (tmp_path / "Git.md").write_text("旧内容", encoding="utf-8")
    provider = _provider(tmp_path)

    answer = provider.answer("u1", "修改笔记 标题：Git 内容：追加内容", _context())

    assert answer == "已追加到笔记：Git.md"


def test_note_command_rejects_unauthorized_user(tmp_path: Path) -> None:
    provider = _provider(tmp_path)

    answer = provider.answer("u2", "笔记列表", _context())

    assert answer == "你没有权限使用笔记功能。"


def test_note_command_rejects_unknown_user(tmp_path: Path) -> None:
    provider = _provider(tmp_path)

    answer = provider.answer("unknown", "笔记列表", _context())

    assert answer == "无法识别用户身份，已拒绝操作。"


def test_note_command_rejects_guest_user(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    auth_service.grant("owner-1", "u1", "notes", "guest")
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("u1", "笔记列表", _context())

    assert answer == "你没有权限使用笔记功能。"


def test_auth_command_has_priority(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("owner-1", "设置权限 用户：u1 功能：notes 身份：user", _context())

    assert answer == "已设置用户 u1 在 notes 功能的身份为 user。"
    assert auth_service.get_role("u1", "notes") == "user"


def test_admin_can_grant_notes_user_in_provider(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    auth_service.grant("owner-1", "admin-1", "notes", "admin")
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("admin-1", "设置权限 用户：u1 功能：notes 身份：user", _context())

    assert answer == "已设置用户 u1 在 notes 功能的身份为 user。"
    assert auth_service.get_role("u1", "notes") == "user"


def test_user_cannot_grant_permissions_in_provider(tmp_path: Path) -> None:
    provider = _provider(tmp_path)

    answer = provider.answer("u1", "设置权限 用户：u2 功能：notes 身份：user", _context())

    assert answer == "你没有权限设置该功能权限。"


def test_view_my_id(tmp_path: Path) -> None:
    provider = _provider(tmp_path)

    answer = provider.answer("u1", "查看我的ID", _context())

    assert answer == "当前用户ID：u1"
