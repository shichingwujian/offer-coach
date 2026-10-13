"""Query Engine 测试：全程 FakeProvider / 桩 client，不联网、零成本（decisions.md D003）。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx2 as httpx  # openai 3.x 的 HTTP 底层是 httpx2
import openai
import pytest

from offer_coach.engine import (
    EngineConfig,
    FakeProvider,
    Message,
    OpenAIProvider,
    QueryEngine,
    QueryEngineError,
    RetryConfig,
)


def no_sleep(_seconds: float) -> None:
    """测试用 sleep：不真等。"""


def make_engine(script: list[Any], budget: float = 1.0, max_retries: int = 3) -> tuple[QueryEngine, FakeProvider]:
    provider = FakeProvider(script)
    engine = QueryEngine(
        EngineConfig(
            provider=provider,
            budget_usd=budget,
            retry=RetryConfig(max_retries=max_retries, base_delay=0.01),
            sleep=no_sleep,
        )
    )
    return engine, provider


USER_HI = [Message(role="user", content="hi")]


class TestQueryEngine:
    def test_query_success_records_cost(self) -> None:
        engine, _ = make_engine([FakeProvider.text_turn("你好")])
        turn = engine.query(USER_HI)
        assert turn.message.content == "你好"
        assert engine.ledger.requests == 1
        assert engine.ledger.spent_usd > 0

    def test_retry_recovers_from_rate_limit(self) -> None:
        engine, provider = make_engine(
            [QueryEngineError.rate_limit(), FakeProvider.text_turn("恢复成功")]
        )
        turn = engine.query(USER_HI)
        assert turn.message.content == "恢复成功"
        assert len(provider.calls) == 2  # 第 1 次被限流，重试第 2 次成功

    def test_retry_exhausted_raises(self) -> None:
        engine, provider = make_engine(
            [QueryEngineError.rate_limit() for _ in range(3)],
            max_retries=2,
        )
        with pytest.raises(QueryEngineError) as exc_info:
            engine.query(USER_HI)
        assert exc_info.value.category == "rate_limit"
        assert len(provider.calls) == 3  # 1 次原始 + 2 次重试，之后放弃

    def test_invalid_request_not_retried(self) -> None:
        engine, provider = make_engine([QueryEngineError.invalid_request("bad args")])
        with pytest.raises(QueryEngineError) as exc_info:
            engine.query(USER_HI)
        assert exc_info.value.category == "invalid_request"
        assert len(provider.calls) == 1  # 不可重试：只调一次

    def test_budget_exceeded_blocks_call(self) -> None:
        engine, provider = make_engine([FakeProvider.text_turn("不会被用到")], budget=0.0)
        with pytest.raises(QueryEngineError) as exc_info:
            engine.query(USER_HI)
        assert exc_info.value.category == "budget"
        assert len(provider.calls) == 0  # 调用前拉闸：provider 根本没被碰


def _stub_client(result: Any = None, error: Exception | None = None) -> Any:
    """桩 OpenAI client：create() 要么返回预设响应，要么抛预设异常。"""

    def create(**_kwargs: Any) -> Any:
        if error is not None:
            raise error
        return result

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _openai_response(content: str = "文本回答", tool_calls: list[Any] | None = None) -> Any:
    return SimpleNamespace(
        id="req-1",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=tool_calls),
                finish_reason="tool_calls" if tool_calls else "stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


class TestOpenAIProvider:
    def test_translates_text_response(self) -> None:
        provider = OpenAIProvider(_stub_client(result=_openai_response()), model="deepseek-chat")
        turn = provider.complete(USER_HI)
        assert turn.message.content == "文本回答"
        assert turn.stop_reason == "end_turn"
        assert turn.usage.input_tokens == 10
        assert turn.request_id == "req-1"

    def test_translates_tool_call_response(self) -> None:
        tc = SimpleNamespace(
            id="call_42",
            function=SimpleNamespace(name="query_knowledge_base", arguments='{"q":"hash"}'),
        )
        provider = OpenAIProvider(_stub_client(result=_openai_response(None, [tc])), model="m")
        turn = provider.complete(USER_HI)
        assert turn.stop_reason == "tool_use"
        assert turn.message.tool_calls is not None
        assert turn.message.tool_calls[0].id == "call_42"
        assert turn.message.tool_calls[0].name == "query_knowledge_base"

    def test_maps_sdk_rate_limit_to_classified_error(self) -> None:
        req = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
        resp = httpx.Response(429, request=req)
        sdk_error = openai.RateLimitError("slow down", response=resp, body=None)
        provider = OpenAIProvider(_stub_client(error=sdk_error), model="m")
        with pytest.raises(QueryEngineError) as exc_info:
            provider.complete(USER_HI)
        assert exc_info.value.category == "rate_limit"
        assert exc_info.value.retryable is True

    def test_from_env_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(QueryEngineError) as exc_info:
            OpenAIProvider.from_env()
        assert exc_info.value.category == "auth"
        assert "OPENAI_API_KEY" in str(exc_info.value)
