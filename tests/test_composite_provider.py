from pathlib import Path

import pytest

from qqbot_app.auth_service import AuthService, FeatureNames
from qqbot_app.help_service import HelpService
from qqbot_app.providers import AnswerContext, BotMessage, ChatAnswerProvider
from qqbot_app.qa_service import FaqAnswerProvider, FaqItem


class _FakeCocService:
    def get_player_summary(self, player_tag: str) -> str:
        return f"玩家查询结果：{player_tag}"

    def get_building_time_summary(self, player_tag: str) -> str:
        return f"建筑剩余时间查询结果：{player_tag}"

    def get_clan_war_summary(self, clan_tag: str) -> str:
        return f"部落战查询结果：{clan_tag}"

    def get_capital_raid_summary(self, clan_tag: str) -> str:
        return f"都城突袭查询结果：{clan_tag}"

    def get_player_battlelog_summary(self, player_tag: str) -> str:
        return f"战斗日志查询结果：{player_tag}"

    def get_player_league_history_summary(self, player_tag: str) -> str:
        return f"联赛历史查询结果：{player_tag}"


class _FakeWuwaService:
    def request_sms_code(self, user_id: str, mobile: str) -> str:
        return f"发送鸣潮验证码：{user_id}:{mobile}"

    def submit_sms_code(self, user_id: str, code: str) -> str:
        return f"提交鸣潮验证码：{user_id}:{code}"

    def bind_token(self, user_id: str, token: str) -> str:
        return f"绑定Token：{user_id}:{token}"

    def bind_role(self, user_id: str, role_id: str, server_id: str = "") -> str:
        return f"绑定角色：{user_id}:{role_id}:{server_id}"

    def describe_binding(self, user_id: str) -> str:
        return f"鸣潮绑定：{user_id}"

    def delete_binding(self, user_id: str) -> str:
        return f"删除鸣潮绑定：{user_id}"

    def get_profile_summary(self, user_id: str) -> str:
        return f"鸣潮面板：{user_id}"

    def get_stamina_summary(self, user_id: str) -> str:
        return f"鸣潮体力：{user_id}"

    def get_character_summary(self, user_id: str, character_name: str) -> str:
        return f"鸣潮练度：{user_id}:{character_name}"

    def import_gacha_url(self, user_id: str, url: str) -> str:
        return f"导入鸣潮抽卡：{user_id}:{url}"

    def import_gacha_json(self, user_id: str, raw_json: str) -> str:
        return f"导入鸣潮抽卡JSON：{user_id}:{raw_json}"

    def get_gacha_analysis(self, user_id: str, pool_name: str = "") -> str:
        return f"抽卡分析：{user_id}:{pool_name}"


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
    return ChatAnswerProvider(
        faq_provider=_faq_provider(),
        note_root=str(tmp_path),
        auth_service=auth_service,
        coc_service=_FakeCocService(),
        wuwa_service=_FakeWuwaService(),
    )


def _provider_with_help(tmp_path: Path, auth_service: AuthService) -> ChatAnswerProvider:
    return ChatAnswerProvider(
        faq_provider=_faq_provider(),
        note_root=str(tmp_path),
        auth_service=auth_service,
        help_service=HelpService.from_file(Path("config/help.yaml")),
        coc_service=_FakeCocService(),
        wuwa_service=_FakeWuwaService(),
    )


def test_note_command_has_priority(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    auth_service.grant("owner-1", "admin-1", "notes", "admin")
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("admin-1", "新增笔记 标题：功能 内容：笔记内容", _context())

    assert answer == "已新增笔记：功能.md"
    assert (tmp_path / "功能.md").exists()


def test_non_note_message_falls_back_to_faq(tmp_path: Path) -> None:
    provider = _provider_with_auth(tmp_path, AuthService(tmp_path / "auth.yaml"))

    answer = provider.answer("u1", "你能做什么", _context())

    assert answer == "功能回答"


def test_help_command_returns_rich_message(tmp_path: Path) -> None:
    provider = _provider_with_help(tmp_path, AuthService(tmp_path / "auth.yaml"))

    answer = provider.answer("u1", "帮助", _context())

    assert isinstance(answer, BotMessage)
    assert "帮助 笔记" in answer.content


def test_help_command_does_not_override_business_command(tmp_path: Path) -> None:
    (tmp_path / "Git.md").write_text("Git 内容", encoding="utf-8")
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    auth_service.grant("owner-1", "u1", "notes", "user")
    provider = _provider_with_help(tmp_path, auth_service)

    answer = provider.answer("u1", "笔记列表", _context())

    assert answer == "现有笔记：\n- Git"


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


def test_short_read_note_command(tmp_path: Path) -> None:
    (tmp_path / "Git.md").write_text("Git 内容", encoding="utf-8")
    provider = _provider(tmp_path)

    answer = provider.answer("u1", "看笔记：Git", _context())

    assert answer == "Git.md：\nGit 内容"


def test_short_create_note_command_rejects_default_user(tmp_path: Path) -> None:
    provider = _provider(tmp_path)

    answer = provider.answer("u1", "新笔记：Git 笔记内容", _context())

    assert answer == "新增或修改共享笔记需要笔记 admin 或 owner 权限。"
    assert not (tmp_path / "Git.md").exists()


def test_append_note_command_rejects_default_user_without_changing_file(tmp_path: Path) -> None:
    (tmp_path / "Git.md").write_text("旧内容", encoding="utf-8")
    provider = _provider(tmp_path)

    answer = provider.answer("u1", "修改笔记 标题：Git 内容：追加内容", _context())

    assert answer == "新增或修改共享笔记需要笔记 admin 或 owner 权限。"
    assert (tmp_path / "Git.md").read_text(encoding="utf-8") == "旧内容"


def test_short_append_note_command_allowed_for_notes_admin(tmp_path: Path) -> None:
    (tmp_path / "Git.md").write_text("旧内容", encoding="utf-8")
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    auth_service.grant("owner-1", "admin-1", "notes", "admin")
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("admin-1", "改笔记：Git 追加内容", _context())

    assert answer == "已追加到笔记：Git.md"


def test_create_note_command_allowed_for_owner(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("owner-1", "新增笔记 标题：Git 内容：笔记内容", _context())

    assert answer == "已新增笔记：Git.md"
    assert (tmp_path / "Git.md").read_text(encoding="utf-8") == "笔记内容\n"


def test_note_query_allows_default_user(tmp_path: Path) -> None:
    provider = _provider(tmp_path)

    answer = provider.answer("u2", "笔记列表", _context())

    assert answer == "暂无笔记。"


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


def test_clash_command_allowed_for_clash_user(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("u1", "查询玩家：#ABC123", _context())

    assert answer == "玩家查询结果：#ABC123"


def test_short_clash_command_allowed_for_clash_user(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    auth_service.grant("owner-1", "u1", "clash", "user")
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("u1", "玩家：#ABC123", _context())

    assert answer == "玩家查询结果：#ABC123"


def test_clash_command_rejects_guest_user(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    auth_service.grant("owner-1", "u1", "clash", "guest")
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("u1", "查询玩家：#ABC123", _context())

    assert answer == "你没有权限使用部落冲突查询功能。"


def test_invalid_clash_command_returns_format_tip(tmp_path: Path) -> None:
    provider = _provider(tmp_path)

    answer = provider.answer("u1", "查询玩家 #ABC123", _context())

    assert "部落冲突命令格式不正确" in answer


def test_owner_can_grant_clash_permission(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("owner-1", "设置权限 用户：u1 功能：clash 身份：user", _context())

    assert answer == "已设置用户 u1 在 clash 功能的身份为 user。"
    assert auth_service.get_role("u1", "clash") == "user"


def test_clash_building_time_command_allowed_for_clash_user(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    auth_service.grant("owner-1", "u1", "clash", "user")
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("u1", "查询建筑剩余时间：#ABC123", _context())

    assert answer == "建筑剩余时间查询结果：#ABC123"


def test_clash_building_time_command_rejects_guest_user(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    auth_service.grant("owner-1", "u1", "clash", "guest")
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("u1", "查询建筑剩余时间：#ABC123", _context())

    assert answer == "你没有权限使用部落冲突查询功能。"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("查询部落战：#CLAN1", "部落战查询结果：#CLAN1"),
        ("查询都城突袭：#CLAN1", "都城突袭查询结果：#CLAN1"),
        ("查询玩家战斗日志：#PLAYER1", "战斗日志查询结果：#PLAYER1"),
        ("查询玩家联赛历史：#PLAYER1", "联赛历史查询结果：#PLAYER1"),
    ],
)
def test_extra_clash_commands_allowed_for_clash_user(tmp_path: Path, text: str, expected: str) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    auth_service.grant("owner-1", "u1", "clash", "user")
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("u1", text, _context())

    assert answer == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("绑定鸣潮角色：101234567", "绑定角色：u1:101234567:76402e5b20be2c39f095a152090afddc"),
        ("查看鸣潮绑定", "鸣潮绑定：u1"),
        ("删除鸣潮绑定", "删除鸣潮绑定：u1"),
        ("鸣潮面板", "鸣潮面板：u1"),
        ("鸣潮体力", "鸣潮体力：u1"),
        ("练度：今汐", "鸣潮练度：u1:今汐"),
        ("导入鸣潮抽卡：http://example.test", "导入鸣潮抽卡：u1:http://example.test"),
        ('导入鸣潮抽卡JSON：[{"name":"今汐"}]', '导入鸣潮抽卡JSON：u1:[{"name":"今汐"}]'),
        ("抽卡分析：角色活动", "抽卡分析：u1:角色活动"),
    ],
)
def test_wuwa_commands_allowed_for_wuwa_user(tmp_path: Path, text: str, expected: str) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("u1", text, _context())

    assert answer == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("鸣潮登录：13800138000", "发送鸣潮验证码：u1:13800138000"),
        ("鸣潮验证码：123456", "提交鸣潮验证码：u1:123456"),
        ("绑定鸣潮Token：token-1", "绑定Token：u1:token-1"),
    ],
)
def test_wuwa_sms_login_allowed_in_private_chat(tmp_path: Path, text: str, expected: str) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("u1", text, AnswerContext(event_type="c2c_message"))

    assert answer == expected


@pytest.mark.parametrize("text", ["鸣潮登录：13800138000", "鸣潮验证码：123456", "绑定鸣潮Token：token-1"])
def test_wuwa_sms_login_rejected_in_group_chat(tmp_path: Path, text: str) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    auth_service.grant("owner-1", "u1", "wuwa", "user")
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("u1", text, AnswerContext(event_type="group_at_message"))

    assert "只能在私聊中发送" in answer


def test_wuwa_command_rejects_guest_user(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    auth_service.grant("owner-1", "u1", "wuwa", "guest")
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("u1", "鸣潮面板", _context())

    assert answer == "你没有权限使用鸣潮功能。"


def test_invalid_wuwa_command_returns_format_tip(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    auth_service.grant("owner-1", "u1", "wuwa", "user")
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("u1", "绑定鸣潮", _context())

    assert "鸣潮命令格式不正确" in answer


def test_owner_can_grant_wuwa_permission_by_chinese_name(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"], FeatureNames({"wuwa": "鸣潮"}))
    provider = _provider_with_auth(tmp_path, auth_service)

    answer = provider.answer("owner-1", "设置权限 用户：u1 功能：鸣潮 身份：user", _context())

    assert answer == "已设置用户 u1 在 鸣潮 功能的身份为 user。"
    assert auth_service.get_role("u1", "wuwa") == "user"


def test_group_promote_note_permission_uses_target_mention(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"], FeatureNames({"notes": "笔记"}))
    provider = _provider_with_auth(tmp_path, auth_service)
    context = AnswerContext(event_type="group_at_message", extra={"mention_user_ids": ["bot-id", "u1"]})

    answer = provider.answer("owner-1", "@机器人 提升笔记权限 @某某", context)

    assert answer == "已将用户 u1 在 笔记 功能的身份提升为 admin。"
    assert auth_service.get_role("u1", "notes") == "admin"


def test_group_promote_uses_last_non_actor_mention(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"], FeatureNames({"notes": "笔记"}))
    provider = _provider_with_auth(tmp_path, auth_service)
    context = AnswerContext(event_type="group_at_message", extra={"mention_user_ids": ["bot-id", "owner-1", "u1"]})

    answer = provider.answer("owner-1", "提升笔记权限 @某某", context)

    assert answer == "已将用户 u1 在 笔记 功能的身份提升为 admin。"


def test_promote_permission_requires_group_chat(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"], FeatureNames({"notes": "笔记"}))
    provider = _provider_with_auth(tmp_path, auth_service)
    context = AnswerContext(event_type="c2c_message", extra={"mention_user_ids": ["u1"]})

    answer = provider.answer("owner-1", "提升笔记权限 @某某", context)

    assert answer == "提升权限只能在群聊中使用。"


def test_promote_permission_requires_target_mention(tmp_path: Path) -> None:
    auth_service = AuthService(tmp_path / "auth.yaml", ["owner-1"], FeatureNames({"notes": "笔记"}))
    provider = _provider_with_auth(tmp_path, auth_service)
    context = AnswerContext(event_type="group_at_message", extra={"mention_user_ids": ["owner-1"]})

    answer = provider.answer("owner-1", "提升笔记权限", context)

    assert answer == "请 @ 需要提升权限的用户。"
