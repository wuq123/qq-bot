from pathlib import Path
from typing import Any

import httpx2 as httpx
from langchain_core.messages import AIMessage, HumanMessage
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, BadRequestError, RateLimitError

from qqbot_app.agent_tools import AgentToolRegistry
from qqbot_app.bot_message import BotMessage
from qqbot_app.providers import AnswerContext, LangChainAgentProvider, LLMConfig


class _FakeActions:
    def __init__(self, wuwa_result: Any = "鸣潮结果") -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.wuwa_result = wuwa_result

    def handle_note(self, user_id: str, command: Any) -> str:
        self.calls.append(("notes", user_id, command))
        return f"笔记结果：{command.action}:{command.title}"

    def handle_coc(self, user_id: str, command: Any) -> str:
        self.calls.append(("clash", user_id, command))
        return f"玩家结果：{command.player_tag}"

    def handle_wuwa(self, user_id: str, command: Any, context: AnswerContext) -> Any:
        self.calls.append(("wuwa", user_id, command, context))
        return self.wuwa_result

    def handle_auth(self, user_id: str, command: Any, context: AnswerContext) -> str:
        self.calls.append(("permissions", user_id, command, context))
        return f"权限结果：{command.action}"


class _FakeModel:
    def __init__(self, results: list[Any]) -> None:
        self.results = results
        self.calls: list[list[Any]] = []
        self.bound_tools: list[Any] = []
        self.bind_kwargs: dict[str, Any] = {}

    def invoke(self, messages: list[Any]) -> Any:
        self.calls.append(list(messages))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "_FakeModel":
        self.bound_tools = tools
        self.bind_kwargs = kwargs
        return self


class _UnsupportedNativeModel(_FakeModel):
    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "_FakeModel":
        raise NotImplementedError


def _config(context_rounds: int = 5, mode: str = "json", max_iterations: int = 3) -> LLMConfig:
    return LLMConfig(
        enabled=True,
        base_url="https://example.test/v1",
        api_key_env="CUSTOM_LLM_KEY",
        model="test-model",
        context_rounds=context_rounds,
        timeout=12,
        max_tokens=321,
        temperature=0.7,
        tool_call_mode=mode,
        max_tool_iterations=max_iterations,
        confirmation_ttl_seconds=120,
    )


def _registry(actions: Any = None) -> AgentToolRegistry:
    return AgentToolRegistry(actions or _FakeActions(), None)


def _context(conversation_id: str = "chat-1") -> AnswerContext:
    return AnswerContext(event_type="test", extra={"conversation_id": conversation_id})


def _write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "llm.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_llm_config_from_file(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        """enabled: true
base_url: https://example.test/v1
api_key_env: CUSTOM_LLM_KEY
model: replacement-model
context_rounds: 3
timeout: 12.5
max_tokens: 800
temperature: 0.4
tool_call_mode: native
max_tool_iterations: 4
confirmation_ttl_seconds: 60
""",
    )

    config = LLMConfig.from_file(path)

    assert config == LLMConfig(True, "https://example.test/v1", "CUSTOM_LLM_KEY", "replacement-model", 3, 12.5, 800, 0.4, "native", 4, 60)


def test_disabled_llm_config_uses_agent_defaults(tmp_path: Path) -> None:
    config = LLMConfig.from_file(_write_config(tmp_path, "enabled: false\ncontext_rounds: 0\n"))

    assert config.enabled is False
    assert config.context_rounds == 0
    assert config.tool_call_mode == "json"
    assert config.max_tool_iterations == 3
    assert config.confirmation_ttl_seconds == 120


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ('enabled: "yes"', "enabled 必须是布尔值"),
        ("enabled: true", "缺少必要字段"),
        ("enabled: false\ntool_call_mode: other", "tool_call_mode"),
        ("enabled: false\ncontext_rounds: -1", "context_rounds"),
        ("enabled: false\nmax_tool_iterations: 0", "max_tool_iterations"),
        ("enabled: false\nconfirmation_ttl_seconds: 0", "confirmation_ttl_seconds"),
    ],
)
def test_invalid_llm_config_has_clear_error(tmp_path: Path, content: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        LLMConfig.from_file(_write_config(tmp_path, content))


def test_provider_builds_chat_openai_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    model = _FakeModel([AIMessage(content='{"action":"answer","answer":"回答"}')])

    def fake_chat_openai(**kwargs: Any) -> _FakeModel:
        seen.update(kwargs)
        return model

    monkeypatch.setattr("qqbot_app.providers.openai_chat.ChatOpenAI", fake_chat_openai)
    provider = LangChainAgentProvider(_config(), "secret-key", _registry())

    assert provider.answer("u1", "问题", _context()) == "回答"
    assert seen == {
        "api_key": "secret-key",
        "base_url": "https://example.test/v1",
        "model": "test-model",
        "timeout": 12,
        "max_tokens": 321,
        "temperature": 0.7,
    }


def test_json_mode_returns_direct_answer_and_accepts_code_fence() -> None:
    model = _FakeModel([AIMessage(content='```json\n{"action":"answer","answer":"模型回答"}\n```')])
    provider = LangChainAgentProvider(_config(), "key", _registry(), model)

    assert provider.answer("u1", "<@!bot-id> 用户问题", _context()) == "模型回答"
    prompt = model.calls[0][-1].content
    assert "用户问题：用户问题" in prompt
    assert "bot-id" not in prompt
    assert all("u1" not in str(message.content) for message in model.calls[0])


def test_json_mode_accepts_plain_text_as_direct_answer() -> None:
    model = _FakeModel([AIMessage(content="你好！很高兴认识你。")])
    provider = LangChainAgentProvider(_config(), "key", _registry(), model)

    assert provider.answer("u1", "你好", _context()) == "你好！很高兴认识你。"
    assert len(model.calls) == 1


def test_group_answer_uses_only_supplied_text_without_agent_history() -> None:
    model = _FakeModel(
        [
            AIMessage(content='{"action":"answer","answer":"私聊回答"}'),
            AIMessage(content="群聊回答"),
        ]
    )
    provider = LangChainAgentProvider(_config(), "key", _registry(), model)
    provider.answer("private-user", "私聊问题", _context())

    assert provider.answer_group(["前一条", "最后一条"]) == "群聊回答"
    assert len(model.calls[1]) == 1
    prompt = model.calls[1][0].content
    assert "1. 前一条" in prompt
    assert "2. 最后一条" in prompt
    assert "private-user" not in prompt
    assert "私聊问题" not in prompt
    assert "不要调用" in prompt


def test_group_answer_silently_rejects_errors_empty_and_tool_json() -> None:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    model = _FakeModel(
        [
            APITimeoutError(request=request),
            AIMessage(content=""),
            AIMessage(content='{"action":"tool","tool":"notes","arguments":{}}'),
        ]
    )
    provider = LangChainAgentProvider(_config(), "key", _registry(), model)

    assert provider.answer_group(["第一条"]) is None
    assert provider.answer_group(["第二条"]) is None
    assert provider.answer_group(["第三条"]) is None


def test_json_mode_repairs_invalid_decision_once() -> None:
    model = _FakeModel(
        [
            AIMessage(content='{"action":"answer","answer":'),
            AIMessage(content='{"action":"answer","answer":"修复后的回答"}'),
        ]
    )
    provider = LangChainAgentProvider(_config(), "key", _registry(), model)

    assert provider.answer("u1", "问题", _context()) == "修复后的回答"
    assert len(model.calls) == 2
    assert "返回格式无效" in model.calls[1][-1].content


def test_json_mode_falls_back_to_direct_answer_after_two_invalid_decisions() -> None:
    model = _FakeModel(
        [
            AIMessage(content='{"action":"answer","answer":'),
            AIMessage(content='{"action":"tool","tool":'),
            AIMessage(content="这是降级后的直接回答。"),
        ]
    )
    provider = LangChainAgentProvider(_config(), "key", _registry(), model)

    assert provider.answer("u1", "问题", _context()) == "这是降级后的直接回答。"
    assert "不要调用" in model.calls[2][-1].content


def test_json_mode_fallback_does_not_execute_tool_decision() -> None:
    model = _FakeModel(
        [
            AIMessage(content='{"action":"answer","answer":'),
            AIMessage(content='{"action":"tool","tool":'),
            AIMessage(content='{"action":"tool","tool":"clash","arguments":{}}'),
        ]
    )
    provider = LangChainAgentProvider(_config(), "key", _registry(), model)

    assert "换一种更明确的说法" in provider.answer("u1", "问题", _context())


def test_json_mode_executes_text_tool_then_model_summarizes() -> None:
    actions = _FakeActions()
    model = _FakeModel(
        [
            AIMessage(content='{"action":"tool","tool":"clash","arguments":{"action":"player","tag":"#ABC"}}'),
            AIMessage(content='{"action":"answer","answer":"玩家摘要"}'),
        ]
    )
    provider = LangChainAgentProvider(_config(), "key", _registry(actions), model)

    assert provider.answer("u1", "查一下玩家ABC", _context()) == "玩家摘要"
    assert actions.calls[0][0:2] == ("clash", "u1")
    assert "玩家结果：#ABC" in model.calls[1][-1].content


def test_tool_registry_is_allowlisted_and_excludes_wuwa_credentials() -> None:
    registry = _registry()

    assert [tool.name for tool in registry.langchain_tools] == ["notes", "clash", "wuwa", "permissions", "help"]
    with pytest.raises(ValueError):
        registry.prepare("unknown", {})
    with pytest.raises(ValueError):
        registry.prepare("wuwa", {"action": "bind_token", "value": "secret"})


def test_permission_tool_uses_shared_action_service() -> None:
    actions = _FakeActions()
    item, arguments = _registry(actions).prepare(
        "permissions",
        {"action": "grant", "target_user_id": "u2", "feature": "笔记", "role": "user"},
    )

    assert item.mutating(arguments) is True
    assert item.execute(arguments, "owner", _context()) == "权限结果：grant"
    assert actions.calls[0][0:2] == ("permissions", "owner")


def test_rich_tool_result_is_returned_without_second_model_call() -> None:
    rich = BotMessage(content="鸣潮面板", image=b"image")
    actions = _FakeActions(wuwa_result=rich)
    model = _FakeModel(
        [AIMessage(content='{"action":"tool","tool":"wuwa","arguments":{"action":"profile"}}')]
    )
    provider = LangChainAgentProvider(_config(), "key", _registry(actions), model)

    assert provider.answer("u1", "看看我的鸣潮面板", _context()) is rich
    assert len(model.calls) == 1


def test_mutating_tool_requires_confirmation_in_same_conversation() -> None:
    actions = _FakeActions()
    model = _FakeModel(
        [AIMessage(content='{"action":"tool","tool":"notes","arguments":{"action":"create","title":"Git","content":"secret body"}}')]
    )
    provider = LangChainAgentProvider(_config(), "key", _registry(actions), model)

    pending = provider.answer("u1", "帮我创建Git笔记", _context("chat-1"))

    assert "待确认操作：创建笔记《Git》" in pending
    assert "secret body" not in pending
    assert actions.calls == []
    assert provider.answer("u1", "确认执行", _context("chat-2")) == "当前会话没有待确认操作。"
    assert provider.answer("u1", "确认执行", _context("chat-1")) == "笔记结果：create:Git"
    assert actions.calls[0][0] == "notes"


def test_pending_tool_can_be_cancelled_or_expire() -> None:
    now = [100.0]
    actions = _FakeActions()
    model = _FakeModel(
        [
            AIMessage(content='{"action":"tool","tool":"wuwa","arguments":{"action":"delete_binding"}}'),
            AIMessage(content='{"action":"tool","tool":"wuwa","arguments":{"action":"delete_binding"}}'),
        ]
    )
    provider = LangChainAgentProvider(_config(), "key", _registry(actions), model, clock=lambda: now[0])

    provider.answer("u1", "删除绑定", _context())
    assert provider.answer("u1", "取消执行", _context()) == "已取消待确认操作。"
    provider.answer("u1", "删除绑定", _context())
    now[0] = 221.0
    assert "已过期" in provider.answer("u1", "确认执行", _context())
    assert actions.calls == []


def test_native_mode_binds_and_executes_one_tool() -> None:
    actions = _FakeActions()
    model = _FakeModel(
        [
            AIMessage(content="", tool_calls=[{"name": "clash", "args": {"action": "player", "tag": "#ABC"}, "id": "call-1", "type": "tool_call"}]),
            AIMessage(content="原生工具回答"),
        ]
    )
    provider = LangChainAgentProvider(_config(mode="native"), "key", _registry(actions), model)

    assert provider.answer("u1", "查询玩家", _context()) == "原生工具回答"
    assert [tool.name for tool in model.bound_tools] == ["notes", "clash", "wuwa", "permissions", "help"]
    assert model.bind_kwargs == {"parallel_tool_calls": False}
    assert model.calls[1][-1].content == "玩家结果：#ABC"


def test_native_mode_has_clear_error_when_model_cannot_bind_tools() -> None:
    with pytest.raises(ValueError, match="不支持 native 工具调用"):
        LangChainAgentProvider(
            _config(mode="native"),
            "key",
            _registry(),
            _UnsupportedNativeModel([]),
        )


def test_native_mode_rejects_parallel_tool_calls() -> None:
    calls = [
        {"name": "clash", "args": {"action": "player", "tag": "#A"}, "id": "1", "type": "tool_call"},
        {"name": "clash", "args": {"action": "player", "tag": "#B"}, "id": "2", "type": "tool_call"},
    ]
    model = _FakeModel([AIMessage(content="", tool_calls=calls)])
    provider = LangChainAgentProvider(_config(mode="native"), "key", _registry(), model)

    assert "多个工具" in provider.answer("u1", "查询两个玩家", _context())


def test_tool_iteration_limit_stops_agent() -> None:
    decision = AIMessage(content='{"action":"tool","tool":"clash","arguments":{"action":"player","tag":"#ABC"}}')
    model = _FakeModel([decision, decision])
    provider = LangChainAgentProvider(_config(max_iterations=1), "key", _registry(), model)

    assert "调用次数超过限制" in provider.answer("u1", "一直查", _context())


def test_history_is_trimmed_and_isolated_by_user() -> None:
    model = _FakeModel(
        [
            AIMessage(content='{"action":"answer","answer":"a1"}'),
            AIMessage(content='{"action":"answer","answer":"a2"}'),
            AIMessage(content='{"action":"answer","answer":"a3"}'),
            AIMessage(content='{"action":"answer","answer":"other"}'),
        ]
    )
    provider = LangChainAgentProvider(_config(context_rounds=1), "key", _registry(), model)

    provider.answer("u1", "q1", _context())
    provider.answer("u1", "q2", _context())
    provider.answer("u1", "q3", _context())
    provider.answer("u2", "qx", _context())

    assert [message.content for message in model.calls[2][:-1]] == ["q2", "a2"]
    assert len(model.calls[3]) == 1


def test_zero_context_rounds_does_not_keep_history() -> None:
    model = _FakeModel(
        [
            AIMessage(content='{"action":"answer","answer":"a1"}'),
            AIMessage(content='{"action":"answer","answer":"a2"}'),
        ]
    )
    provider = LangChainAgentProvider(_config(context_rounds=0), "key", _registry(), model)

    provider.answer("u1", "q1", _context())
    provider.answer("u1", "q2", _context())

    assert len(model.calls[1]) == 1


def test_failed_turn_is_not_added_to_history() -> None:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    model = _FakeModel([APITimeoutError(request=request), AIMessage(content='{"action":"answer","answer":"a2"}')])
    provider = LangChainAgentProvider(_config(), "key", _registry(), model)

    assert "超时" in provider.answer("u1", "q1", _context())
    assert provider.answer("u1", "q2", _context()) == "a2"
    assert len(model.calls[1]) == 1


@pytest.mark.parametrize(
    ("exception_factory", "expected"),
    [
        (lambda request, response: AuthenticationError("auth", response=response(401), body=None), "鉴权失败"),
        (lambda request, response: RateLimitError("rate", response=response(429), body=None), "过于频繁"),
        (lambda request, response: APITimeoutError(request=request), "请求超时"),
        (lambda request, response: APIConnectionError(request=request), "无法连接"),
        (lambda request, response: BadRequestError("bad", response=response(400), body=None), "拒绝了本次请求"),
        (lambda request, response: APIStatusError("server", response=response(500), body=None), "暂时不可用"),
    ],
)
def test_provider_maps_openai_errors(exception_factory: Any, expected: str) -> None:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")

    def response(status: int) -> httpx.Response:
        return httpx.Response(status, request=request)

    model = _FakeModel([exception_factory(request, response)])
    provider = LangChainAgentProvider(_config(), "key", _registry(), model)

    assert expected in provider.answer("u1", "q1", _context())
