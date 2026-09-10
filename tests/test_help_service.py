from pathlib import Path

import pytest

from qqbot_app.help_service import HelpService
from qqbot_app.providers import BotMessage


def test_help_root_returns_rich_feature_list() -> None:
    answer = HelpService.from_file(Path("config/help.yaml")).answer("帮助")

    assert isinstance(answer, BotMessage)
    assert "帮助 笔记" in answer.content
    assert answer.markdown == {"content": answer.content}
    assert answer.keyboard is not None
    assert answer.keyboard["content"]["rows"][0]["buttons"][0]["action"]["data"] == "帮助 笔记"


def test_help_feature_returns_detail_and_short_commands() -> None:
    answer = HelpService.from_file(Path("config/help.yaml")).answer("帮助 部落冲突")

    assert isinstance(answer, BotMessage)
    assert "COC_API_TOKEN" in answer.content
    assert "玩家：#TAG" in answer.content
    assert answer.keyboard is not None
    action = answer.keyboard["content"]["rows"][0]["buttons"][0]["action"]
    assert action["data"] == "玩家："
    assert action["enter"] is False


def test_note_query_button_waits_for_user_input() -> None:
    answer = HelpService.from_file(Path("config/help.yaml")).answer("帮助 笔记")

    assert isinstance(answer, BotMessage)
    assert "看笔记：Git" in answer.content
    assert answer.keyboard is not None
    action = answer.keyboard["content"]["rows"][0]["buttons"][1]["action"]
    assert action["data"] == "看笔记："
    assert action["enter"] is False


def test_buttons_without_parameters_enter_directly() -> None:
    answer = HelpService.from_file(Path("config/help.yaml")).answer("帮助 笔记")

    assert isinstance(answer, BotMessage)
    assert answer.keyboard is not None
    action = answer.keyboard["content"]["rows"][0]["buttons"][0]["action"]
    assert action["data"] == "笔记列表"
    assert action["enter"] is True


def test_auth_parameter_button_waits_for_user_input() -> None:
    answer = HelpService.from_file(Path("config/help.yaml")).answer("帮助 权限")

    assert isinstance(answer, BotMessage)
    assert answer.keyboard is not None
    action = answer.keyboard["content"]["rows"][1]["buttons"][0]["action"]
    assert action["data"] == "设置权限 用户："
    assert action["enter"] is False


def test_button_enter_defaults_to_true(tmp_path: Path) -> None:
    path = tmp_path / "help.yaml"
    path.write_text(
        "features:\n"
        "  - key: test\n"
        "    title: 测试\n"
        "    buttons:\n"
        "      - label: 测试\n"
        "        command: 测试命令\n",
        encoding="utf-8",
    )

    answer = HelpService.from_file(path).answer("帮助 测试")

    assert isinstance(answer, BotMessage)
    assert answer.keyboard is not None
    action = answer.keyboard["content"]["rows"][0]["buttons"][0]["action"]
    assert action["enter"] is True


def test_help_unknown_feature_returns_available_features() -> None:
    answer = HelpService.from_file(Path("config/help.yaml")).answer("帮助 xxx")

    assert isinstance(answer, BotMessage)
    assert "没有找到“xxx”的帮助" in answer.content
    assert "笔记" in answer.content


def test_help_ignores_non_help_text() -> None:
    assert HelpService.from_file(Path("config/help.yaml")).answer("笔记列表") is None


def test_missing_help_file_has_clear_error() -> None:
    with pytest.raises(FileNotFoundError, match="帮助配置文件不存在"):
        HelpService.from_file(Path("config/missing-help.yaml"))
