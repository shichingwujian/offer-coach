"""Context 层测试：桌面管理。全本地逻辑，零模型调用。"""

from __future__ import annotations

from typing import Any

from offer_coach.context import ContextConfig, ContextManager, estimate_tokens
from offer_coach.engine import (
    EngineConfig,
    FakeProvider,
    Message,
    QueryEngine,
    RetryConfig,
)
from offer_coach.tools import ToolDef, ToolRegistry, run_loop


def no_sleep(_seconds: float) -> None:
    """测试用 sleep：不真等。"""


def make_engine(script: list[Any]) -> tuple[QueryEngine, FakeProvider]:
    provider = FakeProvider(script)
    engine = QueryEngine(
        EngineConfig(provider=provider, retry=RetryConfig(base_delay=0.01), sleep=no_sleep)
    )
    return engine, provider


class TestEstimateTokens:
    def test_chinese_heavier_than_english(self) -> None:
        # 同样 20 个字符：中文按 1 字 1 token，英文按 4 字符 1 token
        assert estimate_tokens("面试诊断报告共二十个中文字符呀呀呀呀") > estimate_tokens("aaaaaaaaaaaaaaaaaaaa")


class TestFit:
    def test_short_history_unchanged(self) -> None:
        cm = ContextManager()
        msgs = [Message(role="system", content="剧本"), Message(role="user", content="开始")]
        assert cm.fit(msgs) == msgs  # 预算内：一条不动

    def test_long_history_keeps_pinned_and_recent(self) -> None:
        cm = ContextManager(ContextConfig(max_tokens=200, keep_recent=2, reserve_output=50))
        msgs = [
            Message(role="system", content="剧本"),
            Message(role="user", content="任务"),
            *[Message(role="assistant", content=f"老消息{i}" + "长" * 50) for i in range(10)],
            Message(role="user", content="最新的问题"),
        ]
        result = cm.fit(msgs)
        assert result[0].content == "剧本"  # 死保：剧本
        assert result[1].content == "任务"  # 死保：任务锚点
        assert result[-1].content == "最新的问题"  # 最近的在
        assert len(result) < len(msgs)  # 中间老的被扔了

    def test_no_orphan_tool_messages(self) -> None:
        """孤儿订单防线：留下的每条 tool 消息，它的订单也必须留下。"""
        cm = ContextManager(ContextConfig(max_tokens=150, keep_recent=0, reserve_output=50))
        big = "长" * 100  # 够重，逼出裁剪
        msgs = [
            Message(role="system", content="剧本"),
            Message(role="user", content="任务" + big),
        ]
        # 中间塞 5 轮"下单→回执"
        for i in range(5):
            from offer_coach.engine import ToolCall
            msgs.append(Message(role="assistant", content=None,
                                tool_calls=[ToolCall(id=f"c{i}", name="t", arguments=big)]))
            msgs.append(Message(role="tool", tool_call_id=f"c{i}", content=big))
        result = cm.fit(msgs)

        order_ids = {
            tc.id for m in result for tc in (m.tool_calls or [])
        }
        for m in result:
            if m.role == "tool":
                assert m.tool_call_id in order_ids  # 每条回执都有订单，没有孤儿

    def test_keep_recent_survives_even_over_budget(self) -> None:
        cm = ContextManager(ContextConfig(max_tokens=10, keep_recent=2, reserve_output=1))
        msgs = [
            Message(role="system", content="剧本"),
            Message(role="user", content="任务"),
            Message(role="assistant", content="近1" + "长" * 100),
            Message(role="assistant", content="近2" + "长" * 100),
        ]
        result = cm.fit(msgs)
        assert result[-2].content.startswith("近1")  # keep_recent 保底：超预算也不扔


class TestLoopIntegration:
    def test_outbound_history_trimmed_but_internal_intact(self) -> None:
        """发给模型的历史被裁剪；内部完整历史照常累积（记账/配对不受损）。"""
        cm = ContextManager(ContextConfig(max_tokens=120, keep_recent=2, reserve_output=20))
        registry = ToolRegistry()
        registry.register(ToolDef(
            name="noop", description="测试工具",
            parameters={"type": "object", "properties": {}},
            func=lambda: "ok",
        ))
        engine, provider = make_engine([
            FakeProvider.tool_turn("noop", "{}", call_id="c1"),
            FakeProvider.tool_turn("noop", '{"x":1}', call_id="c2"),
            FakeProvider.text_turn("完成"),
        ])
        big_history = [
            Message(role="system", content="剧本"),
            Message(role="user", content="任务" + "长" * 300),  # 超重任务描述
        ]
        result = run_loop(engine, registry, big_history, context=cm)

        assert result.status == "completed"
        assert len(result.messages) > len(provider.calls[-1])  # 内部完整 > 发出被裁
        # 最后一次发出的历史里，剧本死保
        assert provider.calls[-1][0].content == "剧本"
