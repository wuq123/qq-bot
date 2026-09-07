from pathlib import Path

import pytest

from qqbot_app.providers import AnswerContext
from qqbot_app.qa_service import FaqAnswerProvider, FaqItem


def _provider() -> FaqAnswerProvider:
    return FaqAnswerProvider(
        fallback_answer="兜底回答",
        empty_answer="空消息回答",
        help_answer="帮助回答",
        items=[
            FaqItem(question="你能做什么", keywords=["功能", "帮助"], answer="功能回答"),
            FaqItem(question="如何接入LLM", keywords=["LLM", "大模型"], answer="LLM回答"),
        ],
    )


def _context() -> AnswerContext:
    return AnswerContext(event_type="test")


def test_exact_question_match() -> None:
    assert _provider().answer("u1", "你能做什么", _context()) == "功能回答"


def test_exact_question_match_after_mention() -> None:
    assert _provider().answer("u1", "<@!123456> 你能做什么", _context()) == "功能回答"


def test_keyword_match() -> None:
    assert _provider().answer("u1", "请问怎么接入大模型？", _context()) == "LLM回答"


def test_empty_message() -> None:
    assert _provider().answer("u1", "   ", _context()) == "空消息回答"


def test_fallback_answer() -> None:
    assert _provider().answer("u1", "未知问题", _context()) == "兜底回答"


def test_help_answer() -> None:
    assert _provider().answer("u1", "帮助", _context()) == "帮助回答"


def test_load_faq_from_file() -> None:
    provider = FaqAnswerProvider.from_file(Path("config/faq.yaml"))
    answer = provider.answer("u1", "如何修改FAQ", _context())
    assert "config/faq.yaml" in answer


def test_missing_faq_file_has_clear_error() -> None:
    with pytest.raises(FileNotFoundError, match="FAQ 配置文件不存在"):
        FaqAnswerProvider.from_file(Path("config/missing.yaml"))
