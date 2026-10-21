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
from offer_coach.hooks import HookPipeline, truncate_hook
from offer_coach.knowledge import build_db, build_vectors
from offer_coach.knowledge.embedder import FakeEmbedder
from offer_coach.tools import (
    ToolBudget,
    ToolDef,
    ToolRegistry,
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

    def test_query_tool_uses_hybrid_and_reports_channel(self, tmp_path: Path) -> None:
        """正式工具换内脏：字面查不到的题，向量通道能顶上来。"""
        title = "什么是分布式锁？"
        body = "Redis 可实现，SETNX 语义。"
        src = tmp_path / "bank"
        (src / "01-t").mkdir(parents=True)
        (src / "01-t" / "index.md").write_text(
            f"### Q：{title}\n\n{body}\n", encoding="utf-8"
        )
        db = tmp_path / "q.db"
        build_db(src, db)
        embedder = FakeEmbedder({"跨进程互斥怎么搞": [1.0, 0.0], f"{title}\n{body}": [1.0, 0.0]}, dim=2)
        build_vectors(db, embedder)
        engine, _ = make_engine([])

        registry = default_registry(engine, db, embedder=embedder)
        result = execute_tool(
            registry,
            ToolCall(id="c1", name="query_knowledge_base", arguments='{"keyword": "跨进程互斥怎么搞"}'),
        )

        assert "检索模式：hybrid" in result
        assert title in result


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
        assert len(result.trace) == 2
        first_turn = result.trace[0]
        assert first_turn.stop_reason == "tool_use"
        tool_trace = first_turn.tool_traces[0]
        assert tool_trace.call_id == "call_1"
        assert tool_trace.outcome == "success"
        assert tool_trace.repeat_count == 1
        assert "RDB" in tool_trace.result_preview
        assert result.trace[1].stop_reason == "end_turn"
        assert result.trace[1].tool_traces == []

    def test_unknown_tool_loop_survives(self, kb_db: Path) -> None:
        engine, _ = make_engine([
            FakeProvider.tool_turn("nonexistent_tool", "{}"),
            FakeProvider.text_turn("抱歉，我换用已有工具。"),
        ])
        result = run_loop(engine, default_registry(engine, kb_db), USER_ASK)
        assert result.status == "completed"
        assert "不存在" in (result.messages[2].content or "")  # 错误当数据喂回去了
        tool_trace = result.trace[0].tool_traces[0]
        assert tool_trace.outcome == "error"
        assert "不存在" in tool_trace.result_preview

    def test_stuck_on_third_identical_call(self, kb_db: Path) -> None:
        engine, provider = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c1"),
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c2"),
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c3"),
        ])
        result = run_loop(engine, default_registry(engine, kb_db), USER_ASK)
        assert result.status == "stuck"  # 同一动作第 3 次：哨兵止损
        assert len(provider.calls) == 3
        tool_traces = [turn.tool_traces[0] for turn in result.trace]
        assert [trace.outcome for trace in tool_traces] == ["success", "success", "duplicate"]
        assert [trace.repeat_count for trace in tool_traces] == [1, 2, 3]
        assert [m.role for m in result.messages].count("tool") == 2  # 第三次只声明，未执行

    def test_max_iterations_stops_distinct_calls(self, kb_db: Path) -> None:
        engine, _ = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", f'{{"keyword": "k{i}"}}', call_id=f"c{i}")
            for i in range(5)
        ])
        result = run_loop(engine, default_registry(engine, kb_db), USER_ASK, max_iterations=2)
        assert result.status == "max_iterations"
        assert result.iterations == 2
        assert len(result.trace) == 2
        assert [turn.tool_traces[0].arguments for turn in result.trace] == [
            '{"keyword": "k0"}',
            '{"keyword": "k1"}',
        ]

    def test_empty_tool_result_is_traced(self) -> None:
        engine, _ = make_engine([
            FakeProvider.tool_turn("empty_tool", "{}"),
            FakeProvider.text_turn("工具没有返回内容，我直接收尾。"),
        ])
        registry = ToolRegistry()
        registry.register(ToolDef(
            name="empty_tool",
            description="测试空结果",
            parameters={"type": "object", "properties": {}},
            func=lambda: "",
        ))

        result = run_loop(engine, registry, USER_ASK)

        tool_trace = result.trace[0].tool_traces[0]
        assert tool_trace.outcome == "empty"
        assert tool_trace.result_chars == 0
        assert tool_trace.result_preview == ""

    def test_blocked_tool_result_is_traced(self) -> None:
        engine, _ = make_engine([
            FakeProvider.tool_turn("dangerous_tool", "{}"),
            FakeProvider.text_turn("权限不足，我直接说明情况。"),
        ])
        registry = ToolRegistry()
        registry.register(ToolDef(
            name="dangerous_tool",
            description="测试权限拦截",
            parameters={"type": "object", "properties": {}},
            func=lambda: "不应执行",
        ))
        hooks = HookPipeline()
        hooks.add_pre(lambda _name, _args: (False, "测试拦截"))

        result = run_loop(engine, registry, USER_ASK, hooks=hooks)

        tool_trace = result.trace[0].tool_traces[0]
        assert tool_trace.outcome == "blocked"
        assert tool_trace.result_preview == "测试拦截"

    def test_truncated_tool_result_is_traced(self, kb_db: Path) -> None:
        engine, _ = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}'),
            FakeProvider.text_turn("根据截断后的结果收尾。"),
        ])
        hooks = HookPipeline()
        hooks.add_post(truncate_hook(20))

        result = run_loop(engine, default_registry(engine, kb_db), USER_ASK, hooks=hooks)

        tool_trace = result.trace[0].tool_traces[0]
        assert tool_trace.truncated is True
        assert tool_trace.result_chars == len(result.messages[2].content or "")
        assert "已截断" in tool_trace.result_preview

    def test_total_budget_adds_receipt_and_finalizes(self, kb_db: Path) -> None:
        engine, provider = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c1"),
            FakeProvider.tool_turn("generate_report", '{"analysis": "已有分析"}', call_id="c2"),
            FakeProvider.text_turn("基于已有材料收尾。"),
        ])

        result = run_loop(
            engine,
            default_registry(engine, kb_db),
            USER_ASK,
            budget=ToolBudget(max_total_calls=1),
        )

        assert result.status == "completed"
        assert result.iterations == 3  # 第2轮超预算，第3轮是无工具收尾
        assert result.trace[0].tool_traces[0].outcome == "success"
        budget_trace = result.trace[1].tool_traces[0]
        assert budget_trace.outcome == "budget_exceeded"
        assert budget_trace.budget_scope == "total"
        assert budget_trace.repeat_count == 1
        assert result.trace[2].mode == "finalize"
        receipt = result.messages[4]
        assert receipt.tool_call_id == "c2"
        assert "预算已耗尽" in (receipt.content or "")
        assert provider.calls[-1][-1].tool_call_id == "c2"  # 收尾前已补回执

    def test_per_tool_budget_adds_receipt_and_finalizes(self, kb_db: Path) -> None:
        engine, _ = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c1"),
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "持久化"}', call_id="c2"),
            FakeProvider.text_turn("不再查库，直接收尾。"),
        ])

        result = run_loop(
            engine,
            default_registry(engine, kb_db),
            USER_ASK,
            budget=ToolBudget(max_calls_by_tool={"query_knowledge_base": 1}),
        )

        assert result.status == "completed"
        budget_trace = result.trace[1].tool_traces[0]
        assert budget_trace.outcome == "budget_exceeded"
        assert budget_trace.budget_scope == "tool"

    def test_budget_exhaustion_at_last_iteration_still_gets_finalize_turn(self, kb_db: Path) -> None:
        engine, _ = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c1"),
            FakeProvider.text_turn("最后收尾。"),
        ])

        result = run_loop(
            engine,
            default_registry(engine, kb_db),
            USER_ASK,
            max_iterations=1,
            budget=ToolBudget(max_total_calls=0),
        )

        assert result.status == "completed"
        assert result.iterations == 2  # 收尾轮是正常轮数之外的最后一次无工具调用
        assert [turn.mode for turn in result.trace] == ["normal", "finalize"]

    def test_finalize_turn_requesting_tool_fails_safely(self, kb_db: Path) -> None:
        engine, _ = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c1"),
            FakeProvider.tool_turn("generate_report", '{"analysis": "已有分析"}', call_id="c2"),
        ])

        result = run_loop(
            engine,
            default_registry(engine, kb_db),
            USER_ASK,
            budget=ToolBudget(max_total_calls=0),
        )

        assert result.status == "tool_budget_exceeded"
        final_trace = result.trace[-1].tool_traces[0]
        assert final_trace.outcome == "budget_exceeded"
        assert result.messages[-1].role == "tool"  # 收尾轮的订单也补了回执
        assert result.messages[-1].tool_call_id == "c2"

    def test_finalize_whitelisted_tool_executes_then_final_answer(self, kb_db: Path) -> None:
        """P0-4：收尾轮白名单工具正常执行，执行完再补一轮真·无工具收尾。"""
        engine, _ = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c1"),
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "持久化"}', call_id="c2"),
            FakeProvider.tool_turn("generate_report", '{"analysis": "已有分析"}', call_id="c3"),
            FakeProvider.text_turn("报告已排版，交付。"),
        ])

        result = run_loop(
            engine,
            default_registry(engine, kb_db),
            USER_ASK,
            budget=ToolBudget(max_total_calls=1),
            finalize_tools=("generate_report",),
        )

        assert result.status == "completed"
        assert result.final_text == "报告已排版，交付。"
        assert [turn.mode for turn in result.trace] == ["normal", "normal", "finalize", "finalize"]
        assert result.trace[1].tool_traces[0].outcome == "budget_exceeded"  # c2 超总预算
        whitelist_trace = result.trace[2].tool_traces[0]
        assert whitelist_trace.name == "generate_report"
        assert whitelist_trace.outcome == "success"  # 白名单放行且执行成功
        assert result.trace[3].tool_traces == []  # 真·无工具收尾：只交终答
        # 白名单订单的回执挂回历史，模型是看着排版结果写的终答
        assert "面试诊断报告" in (result.messages[-2].content or "")

    def test_finalize_whitelist_excludes_other_tools(self, kb_db: Path) -> None:
        """白名单只放行点名的工具：收尾轮仍想查库，照旧补回执止损。"""
        engine, _ = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c1"),
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "持久化"}', call_id="c2"),
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "AOF"}', call_id="c3"),
        ])

        result = run_loop(
            engine,
            default_registry(engine, kb_db),
            USER_ASK,
            budget=ToolBudget(max_total_calls=1),
            finalize_tools=("generate_report",),
        )

        assert result.status == "tool_budget_exceeded"
        final_trace = result.trace[-1].tool_traces[0]
        assert final_trace.name == "query_knowledge_base"
        assert final_trace.outcome == "budget_exceeded"

    def test_failed_tool_call_still_counts_toward_budget(self, kb_db: Path) -> None:
        engine, _ = make_engine([
            FakeProvider.tool_turn("nonexistent_tool", "{}", call_id="c1"),
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c2"),
            FakeProvider.text_turn("工具失败后也按预算收尾。"),
        ])

        result = run_loop(
            engine,
            default_registry(engine, kb_db),
            USER_ASK,
            budget=ToolBudget(max_total_calls=1),
        )

        assert result.status == "completed"
        assert result.trace[0].tool_traces[0].outcome == "error"
        assert result.trace[1].tool_traces[0].outcome == "budget_exceeded"
