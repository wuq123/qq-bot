from collections import deque
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Deque, Dict, Literal, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAIError,
    RateLimitError,
)
from pydantic import BaseModel, Field, ValidationError, model_validator
import yaml

from qqbot_app.agent_tools import AgentToolRegistry, RegisteredTool
from qqbot_app.bot_message import BotAnswer, BotMessage
from qqbot_app.providers.base import AnswerContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool
    base_url: str
    api_key_env: str
    model: str
    context_rounds: int
    timeout: float
    max_tokens: int
    temperature: float
    tool_call_mode: str = "json"
    max_tool_iterations: int = 3
    confirmation_ttl_seconds: int = 120

    @classmethod
    def from_file(cls, path: Path) -> "LLMConfig":
        if not path.exists():
            raise FileNotFoundError(f"LLM 配置文件不存在: {path}")

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.from_data(data)

    @classmethod
    def from_data(cls, data: Dict[str, Any]) -> "LLMConfig":
        if not isinstance(data, dict):
            raise ValueError("LLM 配置必须是 YAML 对象。")

        enabled = data.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("LLM 配置 enabled 必须是布尔值。")

        base_url = str(data.get("base_url", "")).strip()
        api_key_env = str(data.get("api_key_env", "")).strip()
        model = str(data.get("model", "")).strip()
        if enabled:
            missing = [
                name
                for name, value in (
                    ("base_url", base_url),
                    ("api_key_env", api_key_env),
                    ("model", model),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"LLM 配置缺少必要字段: {', '.join(missing)}")

        tool_call_mode = str(data.get("tool_call_mode", "json")).strip().lower()
        if tool_call_mode not in {"json", "native"}:
            raise ValueError("LLM 配置 tool_call_mode 只能是 json 或 native。")

        return cls(
            enabled=enabled,
            base_url=base_url,
            api_key_env=api_key_env,
            model=model,
            context_rounds=_read_int(data, "context_rounds", 5, minimum=0),
            timeout=_read_number(data, "timeout", 30, minimum=0, inclusive=False),
            max_tokens=_read_int(data, "max_tokens", 1024, minimum=1),
            temperature=_read_number(data, "temperature", 1.0, minimum=0, maximum=2),
            tool_call_mode=tool_call_mode,
            max_tool_iterations=_read_int(data, "max_tool_iterations", 3, minimum=1),
            confirmation_ttl_seconds=_read_int(data, "confirmation_ttl_seconds", 120, minimum=1),
        )


class AgentDecision(BaseModel):
    action: Literal["answer", "tool"]
    answer: Optional[str] = None
    tool: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "AgentDecision":
        if self.action == "answer" and not str(self.answer or "").strip():
            raise ValueError("answer 不能为空")
        if self.action == "tool" and not str(self.tool or "").strip():
            raise ValueError("tool 不能为空")
        return self


@dataclass(frozen=True)
class PendingAction:
    item: RegisteredTool
    arguments: BaseModel
    expires_at: float


@dataclass(frozen=True)
class ToolOutcome:
    result: BotAnswer
    final: bool = False
    pending: bool = False


class LangChainAgentProvider:
    def __init__(
        self,
        config: LLMConfig,
        api_key: str,
        tools: AgentToolRegistry,
        model: Any = None,
        clock: Any = time.monotonic,
    ) -> None:
        self._config = config
        self._tools = tools
        self._model = model or ChatOpenAI(
            api_key=api_key,
            base_url=config.base_url,
            model=config.model,
            timeout=config.timeout,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )
        self._native_model = None
        if config.tool_call_mode == "native":
            try:
                self._native_model = self._model.bind_tools(
                    tools.langchain_tools,
                    parallel_tool_calls=False,
                )
            except (NotImplementedError, ValueError) as exc:
                raise ValueError("当前模型或 LangChain 适配器不支持 native 工具调用，请改用 json 模式。") from exc
        self._history: Dict[str, Deque[BaseMessage]] = {}
        self._pending: Dict[tuple[str, str], PendingAction] = {}
        self._clock = clock

    def answer(self, user_id: str, text: str, context: AnswerContext) -> BotAnswer:
        question = _normalize_text(text)
        if not question:
            return "请发送具体问题。"

        confirmation = self._handle_confirmation(user_id, question, context)
        if confirmation is not None:
            return confirmation

        if self._config.tool_call_mode == "native":
            return self._answer_native(user_id, question, context)
        return self._answer_json(user_id, question, context)

    def answer_group(self, messages: list[str]) -> Optional[str]:
        texts = [str(message).strip() for message in messages if str(message).strip()]
        if not texts:
            return None
        context = "\n".join(f"{index}. {message}" for index, message in enumerate(texts, 1))
        prompt = (
            "你正在参与QQ群聊。请结合最近消息，用贴吧老哥的语气回复最后一条消息。"
            "只输出回复正文，不要输出JSON，不要调用或声称已经调用任何工具。"
            "不得复述、逐条总结、引用或原样返回最近消息；没有合适回复时只输出空字符串。\n"
            f"最近消息：\n{context}"
        )
        response, error_message = _invoke_model(self._model, [HumanMessage(content=prompt)])
        if error_message:
            return None
        answer = _message_text(response).strip()
        if not answer:
            logger.warning("LLM returned an empty OneBot group reply")
            return None
        if _looks_like_decision(answer):
            logger.warning("Ignored tool-like OneBot group reply")
            return None
        return answer

    def _answer_json(self, user_id: str, question: str, context: AnswerContext) -> BotAnswer:
        messages = self._history_messages(user_id)
        messages.append(HumanMessage(content=_json_router_prompt(question, self._tools.prompt_catalog())))
        tool_count = 0
        format_corrected = False

        while True:
            response, error_message = _invoke_model(self._model, messages)
            if error_message:
                return error_message
            response_text = _message_text(response).strip()
            try:
                decision = _parse_decision(response_text)
            except (ValueError, ValidationError):
                if response_text and not _looks_like_decision(response_text):
                    self._remember(user_id, question, response_text)
                    return response_text
                if format_corrected:
                    return self._answer_without_tools(user_id, question)
                format_corrected = True
                messages.extend(
                    [
                        response,
                        HumanMessage(content="返回格式无效。请严格只返回一个JSON对象，不要添加Markdown或解释。"),
                    ]
                )
                continue

            format_corrected = False
            if decision.action == "answer":
                answer = str(decision.answer).strip()
                self._remember(user_id, question, answer)
                return answer

            if tool_count >= self._config.max_tool_iterations:
                return "模型工具调用次数超过限制，请简化问题后重试。"
            tool_count += 1
            outcome = self._execute_tool(decision.tool or "", decision.arguments, user_id, context)
            if outcome.final:
                if isinstance(outcome.result, BotMessage) and not outcome.pending:
                    self._remember(user_id, question, outcome.result.content)
                return outcome.result

            messages.extend(
                [
                    response,
                    HumanMessage(
                        content=(
                            f"工具 {decision.tool} 的执行结果如下：\n{outcome.result}\n"
                            "请基于结果回答原问题；如确有必要，也可继续选择一个工具。仍然只返回JSON对象。"
                        )
                    ),
                ]
            )

    def _answer_without_tools(self, user_id: str, question: str) -> BotAnswer:
        messages = self._history_messages(user_id)
        messages.append(
            HumanMessage(
                content=(
                    "请直接回答下面的问题，不要输出JSON，也不要调用或声称已经调用任何工具，使用贴吧老哥的语气回复问题。"
                    "如果必须使用机器人业务工具才能完成，请让用户换一种更明确的说法。\n"
                    f"用户问题：{question}"
                )
            )
        )
        response, error_message = _invoke_model(self._model, messages)
        if error_message:
            return error_message
        answer = _message_text(response).strip()
        if not answer:
            return "LLM 返回了空回答，请稍后重试。"
        if _looks_like_decision(answer):
            try:
                decision = _parse_decision(answer)
            except (ValueError, ValidationError):
                return "暂时无法理解这个问题，请换一种说法。"
            if decision.action != "answer":
                return "这个问题可能需要机器人功能，请换一种更明确的说法。"
            answer = str(decision.answer).strip()
        self._remember(user_id, question, answer)
        return answer

    def _answer_native(self, user_id: str, question: str, context: AnswerContext) -> BotAnswer:
        messages = self._history_messages(user_id)
        messages.append(HumanMessage(content=question))
        tool_count = 0

        while True:
            response, error_message = _invoke_model(self._native_model, messages)
            if error_message:
                return error_message
            tool_calls = getattr(response, "tool_calls", []) or []
            if not tool_calls:
                answer = _message_text(response).strip()
                if not answer:
                    return "LLM 返回了空回答，请稍后重试。"
                self._remember(user_id, question, answer)
                return answer
            if len(tool_calls) != 1:
                return "模型同时请求了多个工具，当前仅支持逐个调用。"
            if tool_count >= self._config.max_tool_iterations:
                return "模型工具调用次数超过限制，请简化问题后重试。"

            tool_count += 1
            call = tool_calls[0]
            outcome = self._execute_tool(call.get("name", ""), call.get("args", {}), user_id, context)
            if outcome.final:
                if isinstance(outcome.result, BotMessage) and not outcome.pending:
                    self._remember(user_id, question, outcome.result.content)
                return outcome.result
            messages.extend(
                [
                    response,
                    ToolMessage(content=str(outcome.result), tool_call_id=call.get("id", "tool-call")),
                ]
            )

    def _execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        user_id: str,
        context: AnswerContext,
    ) -> ToolOutcome:
        try:
            item, validated = self._tools.prepare(name, arguments)
        except (ValueError, ValidationError) as exc:
            return ToolOutcome(f"工具参数无效：{exc}")

        if item.mutating(validated):
            key = _pending_key(user_id, context)
            self._pending[key] = PendingAction(
                item=item,
                arguments=validated,
                expires_at=self._clock() + self._config.confirmation_ttl_seconds,
            )
            summary = item.summarize(validated)
            return ToolOutcome(
                f"待确认操作：{summary}。\n请在 {self._config.confirmation_ttl_seconds} 秒内发送“确认执行”，或发送“取消执行”。",
                final=True,
                pending=True,
            )

        result = _call_tool(item, validated, user_id, context)
        return ToolOutcome(result, final=isinstance(result, BotMessage))

    def _handle_confirmation(
        self,
        user_id: str,
        question: str,
        context: AnswerContext,
    ) -> Optional[BotAnswer]:
        if question not in {"确认执行", "取消执行"}:
            return None
        key = _pending_key(user_id, context)
        pending = self._pending.pop(key, None)
        if pending is None:
            return "当前会话没有待确认操作。"
        if pending.expires_at < self._clock():
            return "待确认操作已过期，请重新发起。"
        if question == "取消执行":
            return "已取消待确认操作。"
        return _call_tool(pending.item, pending.arguments, user_id, context)

    def _history_messages(self, user_id: str) -> list[BaseMessage]:
        return list(self._history.get(user_id, ()))

    def _remember(self, user_id: str, question: str, answer: str) -> None:
        if self._config.context_rounds == 0:
            return
        history = self._history.setdefault(
            user_id,
            deque(maxlen=self._config.context_rounds * 2),
        )
        history.extend((HumanMessage(content=question), AIMessage(content=answer)))


OpenAIChatProvider = LangChainAgentProvider


def _call_tool(item: RegisteredTool, arguments: BaseModel, user_id: str, context: AnswerContext) -> BotAnswer:
    try:
        return item.execute(arguments, user_id, context)
    except Exception:
        logger.warning("Agent tool execution failed: %s", item.tool.name, exc_info=True)
        return "工具执行失败，请检查参数或稍后重试。"


def _invoke_model(model: Any, messages: list[BaseMessage]) -> tuple[Any, Optional[str]]:
    try:
        return model.invoke(messages), None
    except AuthenticationError:
        logger.warning("LLM authentication failed")
        return None, "LLM 鉴权失败，请联系管理员检查 API Key。"
    except RateLimitError:
        logger.warning("LLM rate limit exceeded")
        return None, "LLM 请求过于频繁，请稍后重试。"
    except APITimeoutError:
        logger.warning("LLM request timed out")
        return None, "LLM 请求超时，请稍后重试。"
    except APIConnectionError:
        logger.warning("LLM connection failed")
        return None, "暂时无法连接 LLM 服务，请稍后重试。"
    except BadRequestError:
        logger.warning("LLM request rejected")
        return None, "LLM 拒绝了本次请求；若使用 native 模式，请确认当前模型支持工具调用。"
    except APIStatusError as exc:
        logger.warning("LLM service returned HTTP status %s", exc.status_code)
        return None, "LLM 服务暂时不可用，请稍后重试。"
    except OpenAIError:
        logger.warning("LLM SDK request failed", exc_info=True)
        return None, "LLM 服务暂时不可用，请稍后重试。"


def _json_router_prompt(question: str, catalog: str) -> str:
    return (
        "你是QQ机器人的决策器。判断用户问题应直接回答还是调用一个工具。"
        "不需要工具时，直接用贴吧老哥的语气回复问题，不要输出JSON。"
        "只有需要工具时才输出JSON对象，不要Markdown；每次只能选择一个工具，不得编造工具。\n"
        '{"action":"tool","tool":"工具名","arguments":{}}\n'
        f"可用工具：{catalog}\n用户问题：{question}"
    )


def _parse_decision(content: str) -> AgentDecision:
    value = content.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end < start:
        raise ValueError("未找到JSON对象")
    data = json.loads(value[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("决策必须是JSON对象")
    return AgentDecision.model_validate(data)


def _looks_like_decision(content: str) -> bool:
    value = content.strip().lower()
    return value.startswith("{") or value.startswith("```json") or '"action"' in value


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return ""


def _pending_key(user_id: str, context: AnswerContext) -> tuple[str, str]:
    conversation_id = str(context.extra.get("conversation_id") or context.event_type)
    return user_id, conversation_id


def _normalize_text(text: str) -> str:
    return re.sub(r"<@!?[^>]+>", "", str(text or "")).strip()


def _read_int(data: Dict[str, Any], name: str, default: int, minimum: int) -> int:
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"LLM 配置 {name} 必须是大于等于 {minimum} 的整数。")
    return value


def _read_number(
    data: Dict[str, Any],
    name: str,
    default: float,
    minimum: float,
    maximum: float | None = None,
    inclusive: bool = True,
) -> float:
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"LLM 配置 {name} 必须是数字。")
    if value < minimum or (not inclusive and value == minimum):
        comparison = "大于等于" if inclusive else "大于"
        raise ValueError(f"LLM 配置 {name} 必须{comparison} {minimum}。")
    if maximum is not None and value > maximum:
        raise ValueError(f"LLM 配置 {name} 必须小于等于 {maximum}。")
    return float(value)
