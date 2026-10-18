"""Skills 层测试：diagnose 菜谱全流程。全程 FakeProvider，不联网、零成本。

模型"下三单"的剧本由 FakeProvider 按脚本演出（D003：测试要确定，真模型给的是惊喜）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from offer_coach.engine import EngineConfig, FakeProvider, QueryEngine, RetryConfig
from offer_coach.knowledge import build_db
from offer_coach.skills import diagnose


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
        assert "3 轮" in message
        assert message.count("query_knowledge_base") == 3
        assert '{"keyword": "Redis"}' in message

    def test_ledger_records_real_cost(self, stage: tuple[Path, Path]) -> None:
        """账本：跑完诊断，engine.ledger 里一定有花销记录（总闸逃不掉票）。"""
        transcript, db = stage
        engine, _ = make_engine([FakeProvider.text_turn("报告")])
        diagnose(transcript, engine, db)
        assert engine.ledger.requests == 1
        assert engine.ledger.spent_usd > 0
