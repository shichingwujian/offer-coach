"""Tools 层测试：全程 FakeProvider + 临时题库，不联网、零成本（decisions.md D003）。

每个测试名 = 一条"输入 X 应输出 Y"的行为说明书。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from offer_coach.engine import (
    EngineConfig,
    FakeProvider,
    Message,
    QueryEngine,
    RetryConfig,
    ToolCall,
)
from offer_coach.knowledge import build_db
from offer_coach.tools import (
    default_registry,
    execute_tool,
    generate_report,
    run_loop,
)


def no_sleep(_seconds: float) -> None:
    """测试用 sleep：不真等。"""


def make_engine(script: list[Any]) -> tuple[QueryEngine, FakeProvider]:
    provider = FakeProvider(script)
    engine = QueryEngine(
        EngineConfig(
            provider=provider,
            retry=RetryConfig(base_delay=0.01),
            sleep=no_sleep,
        )
    )
    return engine, provider


SAMPLE_MD = """## 题目

### Q：Redis 持久化机制有哪些？

RDB 快照和 AOF 日志。
"""


@pytest.fixture
def kb_db(tmp_path: Path) -> Path:
    """临时题库：一道 Redis 题，建在临时目录里。"""
    src = tmp_path / "bank"
    category = src / "01-test"
    category.mkdir(parents=True)
    (category / "index.md").write_text(SAMPLE_MD, encoding="utf-8")
    db = tmp_path / "questions.db"
    build_db(src, db)
    return db


USER_ASK = [Message(role="user", content="帮我诊断这段面试回答")]


class TestTools:
    """三个工具各自的行为。"""

    def test_generate_report_renders_markdown(self) -> None:
        report = generate_report("分析内容", candidate="小张")
        assert report.startswith("# 面试诊断报告")
        assert "小张" in report and "分析内容" in report

    def test_analyze_content_calls_engine(self) -> None:
        engine, provider = make_engine([FakeProvider.text_turn("技术准确性 4 分：……")])
        registry = default_registry(engine, Path("不查库所以这个路径用不上.db"))
        result = execute_tool(
            registry, ToolCall(id="c1", name="analyze_content", arguments='{"transcript": "我答了……"}')
        )
        assert "技术准确性" in result
        assert len(provider.calls) == 1  # 工具内部真的走了一次 engine.query


class TestExecuteTool:
    """执行器的失败路径：全部变成错误文本，绝不抛异常。"""

    def test_unknown_tool_returns_error_text(self, kb_db: Path) -> None:
        engine, _ = make_engine([])
        registry = default_registry(engine, kb_db)
        result = execute_tool(registry, ToolCall(id="c1", name="hack_the_planet", arguments="{}"))
        assert "不存在" in result and "query_knowledge_base" in result  # 顺带告诉模型可用清单

    def test_bad_json_returns_error_text(self, kb_db: Path) -> None:
        engine, _ = make_engine([])
        registry = default_registry(engine, kb_db)
        result = execute_tool(registry, ToolCall(id="c1", name="query_knowledge_base", arguments="{不是json"))
        assert "不是合法 JSON" in result

    def test_missing_required_param_returns_error_text(self, kb_db: Path) -> None:
        engine, _ = make_engine([])
        registry = default_registry(engine, kb_db)
        result = execute_tool(registry, ToolCall(id="c1", name="query_knowledge_base", arguments="{}"))
        assert "缺少必填参数" in result and "keyword" in result


class TestRunLoop:
    """最小 agent loop 的完整旅程。"""

    def test_tool_roundtrip_completes(self, kb_db: Path) -> None:
        engine, provider = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="call_1"),
            FakeProvider.text_turn("根据题库，你应该补上 RDB 和 AOF 的区别。"),
        ])
        result = run_loop(engine, default_registry(engine, kb_db), USER_ASK)

        assert result.status == "completed"
        assert "RDB" in (result.final_text or "")
        roles = [m.role for m in result.messages]
        assert roles == ["user", "assistant", "tool", "assistant"]  # 完整往返
        tool_msg = result.messages[2]
        assert tool_msg.tool_call_id == "call_1"  # 订单号成对挂回
        assert "RDB" in (tool_msg.content or "")  # 工具结果真的进了历史
        assert len(provider.calls) == 2  # 调了两次模型：下单一次、终答一次

    def test_unknown_tool_loop_survives(self, kb_db: Path) -> None:
        engine, _ = make_engine([
            FakeProvider.tool_turn("nonexistent_tool", "{}"),
            FakeProvider.text_turn("抱歉，我换用已有工具。"),
        ])
        result = run_loop(engine, default_registry(engine, kb_db), USER_ASK)
        assert result.status == "completed"
        assert "不存在" in (result.messages[2].content or "")  # 错误当数据喂回去了

    def test_stuck_on_third_identical_call(self, kb_db: Path) -> None:
        engine, provider = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c1"),
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c2"),
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c3"),
        ])
        result = run_loop(engine, default_registry(engine, kb_db), USER_ASK)
        assert result.status == "stuck"  # 同一动作第 3 次：哨兵止损
        assert len(provider.calls) == 3

    def test_max_iterations_stops_distinct_calls(self, kb_db: Path) -> None:
        engine, _ = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", f'{{"keyword": "k{i}"}}', call_id=f"c{i}")
            for i in range(5)
        ])
        result = run_loop(engine, default_registry(engine, kb_db), USER_ASK, max_iterations=2)
        assert result.status == "max_iterations"
        assert result.iterations == 2
