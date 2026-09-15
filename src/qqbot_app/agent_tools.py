from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Dict, Literal, Optional, TYPE_CHECKING, Type

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from qqbot_app.actions import BotActionService
from qqbot_app.auth_service import AuthCommand
from qqbot_app.bot_message import BotAnswer
from qqbot_app.coc_service import CocCommand
from qqbot_app.help_service import HelpService
from qqbot_app.note_service import NoteCommand
from qqbot_app.wuwa_service import WUWA_CN_SERVER_ID, WuwaCommand

if TYPE_CHECKING:
    from qqbot_app.providers.base import AnswerContext


class NoteToolInput(BaseModel):
    action: Literal["list", "read", "create", "append"] = Field(description="笔记操作")
    title: str = Field(default="", description="读取、创建或追加的笔记标题")
    content: str = Field(default="", description="创建或追加的笔记内容")


class ClashToolInput(BaseModel):
    action: Literal["player", "clan_war", "capital_raid", "battlelog", "league_history", "building_time"]
    tag: str = Field(description="玩家或部落标签，例如 #ABC123")


class WuwaToolInput(BaseModel):
    action: Literal[
        "describe_binding",
        "bind_role",
        "delete_binding",
        "profile",
        "stamina",
        "character",
        "import_gacha_url",
        "import_gacha_json",
        "gacha_analysis",
    ]
    value: str = Field(default="", description="角色名、角色ID、导入URL、JSON或卡池名")
    server_id: str = Field(default="", description="绑定角色时可选的区服ID")


class PermissionToolInput(BaseModel):
    action: Literal["me", "describe", "grant", "promote"]
    target_user_id: str = Field(default="", description="目标用户ID；群聊提升可留空并使用被@用户")
    feature: str = Field(default="", description="功能名，例如笔记、部落冲突、鸣潮")
    role: str = Field(default="", description="目标身份 owner、admin、user 或 guest")


class HelpToolInput(BaseModel):
    topic: str = Field(default="", description="帮助主题，例如笔记、部落冲突、鸣潮、权限或FAQ")


@dataclass(frozen=True)
class RegisteredTool:
    tool: StructuredTool
    execute: Callable[[BaseModel, str, AnswerContext], BotAnswer]
    mutating: Callable[[BaseModel], bool]
    summarize: Callable[[BaseModel], str]


class AgentToolRegistry:
    def __init__(self, actions: BotActionService, help_service: Optional[HelpService]) -> None:
        self._tools = _build_tools(actions, help_service)

    @property
    def langchain_tools(self) -> list[StructuredTool]:
        return [item.tool for item in self._tools.values()]

    def prompt_catalog(self) -> str:
        definitions = [
            {
                "name": item.tool.name,
                "description": item.tool.description,
                "parameters": item.tool.args,
            }
            for item in self._tools.values()
        ]
        return json.dumps(definitions, ensure_ascii=False)

    def prepare(self, name: str, arguments: Dict[str, Any]) -> tuple[RegisteredTool, BaseModel]:
        item = self._tools.get(name)
        if item is None:
            raise ValueError(f"未知工具: {name}")
        schema: Type[BaseModel] = item.tool.args_schema
        return item, schema.model_validate(arguments)


def _build_tools(
    actions: BotActionService,
    help_service: Optional[HelpService],
) -> Dict[str, RegisteredTool]:
    return {
        "notes": _registered_tool(
            "notes",
            "列出、读取、创建或追加共享笔记。创建和追加需要笔记管理员权限。",
            NoteToolInput,
            lambda value, user_id, context: actions.handle_note(
                user_id,
                NoteCommand(value.action, value.title, value.content),
            ),
            lambda value: value.action in {"create", "append"},
            lambda value: f"{_action_name(value.action)}笔记《{value.title}》",
        ),
        "clash": _registered_tool(
            "clash",
            "查询部落冲突玩家、部落战、都城突袭、战斗日志、联赛历史或建筑时间限制。",
            ClashToolInput,
            lambda value, user_id, context: actions.handle_coc(
                user_id,
                CocCommand(value.action, value.tag),
            ),
        ),
        "wuwa": _registered_tool(
            "wuwa",
            "查询鸣潮绑定、面板、体力、角色练度和抽卡分析，或绑定角色、导入抽卡、删除绑定。不能处理手机号、验证码和Token。",
            WuwaToolInput,
            lambda value, user_id, context: actions.handle_wuwa(
                user_id,
                WuwaCommand(value.action, value.value, value.server_id or WUWA_CN_SERVER_ID),
                context,
            ),
            lambda value: value.action in {"bind_role", "delete_binding", "import_gacha_url", "import_gacha_json"},
            _summarize_wuwa,
        ),
        "permissions": _registered_tool(
            "permissions",
            "查看当前用户ID或权限，以及设置、提升用户在指定功能中的权限。设置和提升受本地权限规则约束。",
            PermissionToolInput,
            lambda value, user_id, context: actions.handle_auth(
                user_id,
                AuthCommand(value.action, value.target_user_id, value.feature, value.role),
                context,
            ),
            lambda value: value.action in {"grant", "promote"},
            lambda value: f"{_action_name(value.action)}用户 {value.target_user_id or '被@用户'} 的{value.feature}权限{('为 ' + value.role) if value.role else ''}",
        ),
        "help": _registered_tool(
            "help",
            "查看机器人全部功能或指定主题的使用帮助。",
            HelpToolInput,
            lambda value, user_id, context: _help_answer(help_service, value.topic, context),
        ),
    }


def _registered_tool(
    name: str,
    description: str,
    args_schema: Type[BaseModel],
    execute: Callable[[Any, str, AnswerContext], BotAnswer],
    mutating: Callable[[Any], bool] = lambda value: False,
    summarize: Callable[[Any], str] = lambda value: "执行操作",
) -> RegisteredTool:
    def placeholder(**kwargs: Any) -> str:
        return ""

    tool = StructuredTool.from_function(
        func=placeholder,
        name=name,
        description=description,
        args_schema=args_schema,
    )
    return RegisteredTool(tool=tool, execute=execute, mutating=mutating, summarize=summarize)


def _help_answer(help_service: Optional[HelpService], topic: str, context: AnswerContext) -> BotAnswer:
    if help_service is None:
        return "暂未配置帮助功能。"
    hidden_features = set() if context.event_type.startswith("onebot_") else {"blackjack"}
    return help_service.answer(f"帮助 {topic}".strip(), hidden_features) or "没有找到对应帮助。"


def _summarize_wuwa(value: WuwaToolInput) -> str:
    if value.action == "bind_role":
        return f"绑定鸣潮角色 {value.value}"
    if value.action == "delete_binding":
        return "删除当前鸣潮绑定"
    if value.action == "import_gacha_url":
        return "从URL导入鸣潮抽卡记录"
    if value.action == "import_gacha_json":
        return "从JSON导入鸣潮抽卡记录"
    return "执行鸣潮操作"


def _action_name(action: str) -> str:
    return {
        "create": "创建",
        "append": "追加",
        "grant": "设置",
        "promote": "提升",
    }.get(action, action)
