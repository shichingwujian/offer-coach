"""Skills 层测试：diagnose 菜谱全流程。全程 FakeProvider，不联网、零成本。

模型"下三单"的剧本由 FakeProvider 按脚本演出（D003：测试要确定，真模型给的是惊喜）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from offer_coach.engine import EngineConfig, FakeProvider, QueryEngine, QueryEngineError, RetryConfig
from offer_coach.knowledge import build_db, build_vectors
from offer_coach.knowledge.embedder import FakeEmbedder
from offer_coach.knowledge.reranker import FakeReranker
from offer_coach.skills import diagnose, diagnose_run


def no_sleep(_seconds: float) -> None:
    """测试用 sleep：不真等。"""


def make_engine(script: list[Any]) -> tuple[QueryEngine, FakeProvider]:
    provider = FakeProvider(script)
    engine = QueryEngine(
        EngineConfig(provider=provider, retry=RetryConfig(base_delay=0.01), sleep=no_sleep)
    )
    return engine, provider


SAMPLE_MD = """## 题目

### Q：Redis 持久化机制有哪些？

RDB 快照和 AOF 日志。
"""


@pytest.fixture
def stage(tmp_path: Path) -> tuple[Path, Path]:
    """搭舞台：一篇假面试稿 + 一个临时题库。"""
    transcript = tmp_path / "面试稿.txt"
    transcript.write_text("面试官：Redis 持久化有哪些？\n候选人：呃，好像有个 RDB？", encoding="utf-8")
    src = tmp_path / "bank"
    category = src / "01-test"
    category.mkdir(parents=True)
    (category / "index.md").write_text(SAMPLE_MD, encoding="utf-8")
    db = tmp_path / "questions.db"
    build_db(src, db)
    return transcript, db


class TestDiagnose:
    def test_full_pipeline_three_orders(self, stage: tuple[Path, Path]) -> None:
        """剧本演出：模型依次下 analyze → query → report 三单，最后输出报告。"""
        transcript, db = stage
        engine, provider = make_engine([
            FakeProvider.tool_turn("analyze_content", '{"transcript": "稿子内容"}', call_id="c1"),
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c2"),
            FakeProvider.tool_turn("generate_report", '{"analysis": "分析结论", "candidate": "测试员"}', call_id="c3"),
            FakeProvider.text_turn("# 面试诊断报告\n\n最终报告全文"),
        ])
        report = diagnose(transcript, engine, db)

        assert "面试诊断报告" in report
        assert len(provider.calls) == 4  # 三次下单 + 一次终答

    def test_main_flow_uses_hybrid_retrieval_when_embedder_supplied(self, tmp_path: Path) -> None:
        """P1-1：正式诊断路径也走统一检索入口，不是只在评估脚本里用 hybrid。"""
        transcript = tmp_path / "面试稿.txt"
        transcript.write_text("面试官：跨进程互斥怎么搞？\n候选人：不太会。", encoding="utf-8")
        title = "什么是分布式锁？"
        body = "Redis 可实现，SETNX 语义。"
        src = tmp_path / "bank"
        (src / "01-t").mkdir(parents=True)
        (src / "01-t" / "index.md").write_text(f"### Q：{title}\n\n{body}\n", encoding="utf-8")
        db = tmp_path / "questions.db"
        build_db(src, db)
        embedder = FakeEmbedder({"跨进程互斥怎么搞": [1.0, 0.0], f"{title}\n{body}": [1.0, 0.0]}, dim=2)
        build_vectors(db, embedder)
        engine, provider = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "跨进程互斥怎么搞"}', call_id="c1"),
            FakeProvider.text_turn("# 面试诊断报告\n\n最终报告"),
        ])

        result = diagnose_run(transcript, engine, db, embedder=embedder)

        assert result.status == "full"
        tool_receipt = provider.calls[-1][-1].content or ""
        assert "检索模式：hybrid" in tool_receipt
        assert title in tool_receipt

    def test_main_flow_reranker_shows_in_tool_receipt(self, tmp_path: Path) -> None:
        """P2-4：裁判沿 CLI→diagnose_run→工具工厂→统一入口全链条上岗，回执如实报 hybrid+rerank。"""
        transcript = tmp_path / "面试稿.txt"
        transcript.write_text("面试官：跨进程互斥怎么搞？\n候选人：不太会。", encoding="utf-8")
        title = "什么是分布式锁？"
        body = "Redis 可实现，SETNX 语义。"
        src = tmp_path / "bank"
        (src / "01-t").mkdir(parents=True)
        (src / "01-t" / "index.md").write_text(f"### Q：{title}\n\n{body}\n", encoding="utf-8")
        db = tmp_path / "questions.db"
        build_db(src, db)
        embedder = FakeEmbedder({"跨进程互斥怎么搞": [1.0, 0.0], f"{title}\n{body}": [1.0, 0.0]}, dim=2)
        build_vectors(db, embedder)
        engine, provider = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "跨进程互斥怎么搞"}', call_id="c1"),
            FakeProvider.text_turn("# 面试诊断报告\n\n最终报告"),
        ])

        result = diagnose_run(transcript, engine, db, embedder=embedder, reranker=FakeReranker())

        assert result.status == "full"
        tool_receipt = provider.calls[-1][-1].content or ""
        assert "检索模式：hybrid+rerank" in tool_receipt
        assert title in tool_receipt

    def test_kb_budget_adds_receipt_then_finalizes(self, stage: tuple[Path, Path]) -> None:
        """检索预算耗尽：第二次查库不执行，补回执后让模型基于已有材料收尾。"""
        transcript, db = stage
        engine, provider = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c1"),
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "持久化"}', call_id="c2"),
            FakeProvider.text_turn("# 面试诊断报告\n\n基于已有材料收尾"),
        ])

        report = diagnose(transcript, engine, db, max_kb_calls=1)

        assert "基于已有材料收尾" in report
        assert len(provider.calls) == 3  # 两次正常轮 + 一次无工具收尾轮
        assert "调用预算已耗尽" in (provider.calls[-1][-1].content or "")

    def test_model_may_answer_directly(self, stage: tuple[Path, Path]) -> None:
        """模型有权偷懒：不下单直接答，也算 completed。"""
        transcript, db = stage
        engine, _ = make_engine([FakeProvider.text_turn("直接给你的诊断：……")])
        assert "直接给你的诊断" in diagnose(transcript, engine, db)

    def test_stuck_loop_raises(self, stage: tuple[Path, Path]) -> None:
        """模型打转（同一单下 3 次）→ diagnose 明确报错，不许默默吞掉。"""
        transcript, db = stage
        engine, _ = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id=f"c{i}")
            for i in range(3)
        ])
        with pytest.raises(RuntimeError, match="stuck") as exc_info:
            diagnose(transcript, engine, db)
        message = str(exc_info.value)
        assert "degraded" in message
        assert "stuck" in message
        assert "3 轮" in message
        assert message.count("query_knowledge_base") == 3
        assert '{"keyword": "Redis"}' in message
        assert "success" in message
        assert "duplicate（同参数第3次，未执行）" in message
        assert "第3轮(mode=normal, stop=tool_use)" in message

    def test_stuck_with_successful_material_returns_degraded(self, stage: tuple[Path, Path]) -> None:
        """stuck 不是 failed：前面成功查到的题库材料要保留成不完整报告。"""
        transcript, db = stage
        engine, _ = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id=f"c{i}")
            for i in range(3)
        ])

        result = diagnose_run(transcript, engine, db)

        assert result.status == "degraded"
        assert result.loop_status == "stuck"
        assert result.iterations == 3
        assert "面试诊断报告（不完整）" in result.report
        assert "RDB 快照和 AOF 日志" in result.report
        assert "duplicate（同参数第3次，未执行）" in result.report
        assert "stuck" in (result.reason or "")

    def test_finalize_requesting_tool_with_material_returns_degraded(self, stage: tuple[Path, Path]) -> None:
        """收尾轮仍下单：loop 失败，但第一张成功检索回执仍能降级保留。"""
        transcript, db = stage
        engine, _ = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c1"),
            FakeProvider.tool_turn("generate_report", '{"analysis": "已有分析"}', call_id="c2"),
            FakeProvider.tool_turn("generate_report", '{"analysis": "已有分析"}', call_id="c3"),
        ])

        result = diagnose_run(transcript, engine, db, max_tool_calls=1)

        assert result.status == "degraded"
        assert result.loop_status == "tool_budget_exceeded"
        assert "RDB 快照和 AOF 日志" in result.report
        assert "budget_exceeded" in result.report

    def test_no_successful_material_returns_failed(self, stage: tuple[Path, Path]) -> None:
        """工具全错时不能拼假报告：没有成功材料就是 failed。"""
        transcript, db = stage
        engine, _ = make_engine([
            FakeProvider.tool_turn("nonexistent_tool", '{"q": "a"}', call_id="c1"),
            FakeProvider.tool_turn("nonexistent_tool", '{"q": "b"}', call_id="c2"),
        ])

        result = diagnose_run(transcript, engine, db, max_iterations=2)

        assert result.status == "failed"
        assert result.loop_status == "max_iterations"
        assert "面试诊断失败" in result.report
        assert "没有可用于降级报告" in result.report

    def test_empty_final_answer_with_material_returns_degraded(self, stage: tuple[Path, Path]) -> None:
        """completed 但正文为空也不能算 full；有工具材料就降级。"""
        transcript, db = stage
        engine, _ = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c1"),
            FakeProvider.text_turn(""),
        ])

        result = diagnose_run(transcript, engine, db)

        assert result.status == "degraded"
        assert result.loop_status == "completed"
        assert "没有返回报告正文" in (result.reason or "")
        assert "RDB 快照和 AOF 日志" in result.report

    def test_engine_error_returns_failed_without_trace(self, stage: tuple[Path, Path]) -> None:
        """loop 没跑起来时如实 failed：不伪造轮次，也不拼诊断内容。"""
        transcript, db = stage
        engine, _ = make_engine([QueryEngineError.auth("测试密钥错误")])

        result = diagnose_run(transcript, engine, db)

        assert result.status == "failed"
        assert result.loop_status is None
        assert result.iterations is None
        assert "auth" in (result.reason or "")
        assert "面试诊断失败" in result.report

    def test_degraded_still_saves_session(self, stage: tuple[Path, Path], tmp_path: Path) -> None:
        """降级也保存现场：之后可以拿 session 排查或续跑。"""
        transcript, db = stage
        session = tmp_path / "degraded.json"
        engine, _ = make_engine([
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id=f"c{i}")
            for i in range(3)
        ])

        result = diagnose_run(transcript, engine, db, session_path=session)

        assert result.status == "degraded"
        assert session.exists()
        assert "RDB 快照和 AOF 日志" in session.read_text(encoding="utf-8")

    def test_ledger_records_real_cost(self, stage: tuple[Path, Path]) -> None:
        """账本：跑完诊断，engine.ledger 里一定有花销记录（总闸逃不掉票）。"""
        transcript, db = stage
        engine, _ = make_engine([FakeProvider.text_turn("报告")])
        diagnose(transcript, engine, db)
        assert engine.ledger.requests == 1
        assert engine.ledger.spent_usd > 0
