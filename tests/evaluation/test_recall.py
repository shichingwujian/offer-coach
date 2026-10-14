"""召回评估测试：尺子本身要先量准。

评估逻辑用假检索函数测死（确定性），再接真库做端到端冒烟。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from offer_coach.evaluation import EvalCase, format_report, load_eval_set, run_recall
from offer_coach.knowledge.db import build_db, search_questions
from offer_coach.knowledge.parser import Question


def fake_search(mapping: dict[str, list[str]]):
    """假检索函数：查表返回固定结果。评估逻辑不该依赖真 FTS5。"""

    def search(query: str) -> list[Question]:
        return [Question(category="c", title=t, body="") for t in mapping.get(query, [])]

    return search


CASES = [
    EvalCase(query="命中", type="keyword", expect=["题A"]),
    EvalCase(query="落空", type="keyword", expect=["题X"]),
    EvalCase(query="命中2", type="paraphrase", expect=["题B", "题C"]),  # 多答案，中其一即可
]


class TestRunRecall:
    def test_hit_logic_and_breakdown(self) -> None:
        mapping = {"命中": ["题A", "题B"], "落空": ["题B"], "命中2": ["题C"]}
        report = run_recall(CASES, fake_search(mapping), k=5)
        assert (report.hits, report.total) == (2, 3)
        assert report.recall == pytest.approx(2 / 3)
        assert report.by_type["keyword"] == 0.5
        assert report.by_type["paraphrase"] == 1.0
        assert len(report.misses) == 1
        assert report.misses[0].case.query == "落空"  # 漏网清单是改进的调试线索

    def test_k_limits_what_counts(self) -> None:
        """k 之外等于不存在：标准答案排第 2 时，k=1 不中、k=2 中。"""
        mapping = {"q": ["别的题", "题A"]}
        cases = [EvalCase(query="q", type="t", expect=["题A"])]
        assert run_recall(cases, fake_search(mapping), k=1).hits == 0
        assert run_recall(cases, fake_search(mapping), k=2).hits == 1

    def test_empty_set(self) -> None:
        report = run_recall([], fake_search({}), k=5)
        assert report.recall == 0.0 and report.total == 0


class TestLoadEvalSet:
    def test_jsonl_parsing(self, tmp_path: Path) -> None:
        path = tmp_path / "set.jsonl"
        path.write_text(
            '{"query": "q1", "type": "keyword", "expect": ["A", "B"]}\n'
            "\n"  # 空行跳过
            '{"query": "q2", "type": "scenario", "expect": ["C"]}\n',
            encoding="utf-8",
        )
        cases = load_eval_set(path)
        assert len(cases) == 2
        assert cases[0].expect == ["A", "B"]
        assert cases[1].type == "scenario"


class TestRealDbSmoke:
    """端到端：真灌一个小题库，真走 search_questions。"""

    def test_keyword_hit(self, tmp_path: Path) -> None:
        src = tmp_path / "bank"
        (src / "01-t").mkdir(parents=True)
        (src / "01-t" / "index.md").write_text(
            "### Q：什么是余弦相似度？\n\n余弦相似度衡量两个向量的夹角。\n\n"
            "### Q：什么是父子索引？\n\n小块检索、大块返回。\n",
            encoding="utf-8",
        )
        db = tmp_path / "q.db"
        build_db(src, db)
        cases = [
            EvalCase(query="余弦相似度", type="keyword", expect=["什么是余弦相似度？"]),
            EvalCase(query="八竿子打不着的查询词", type="paraphrase", expect=["什么是父子索引？"]),
        ]
        report = run_recall(cases, lambda q: search_questions(db, q, limit=5), k=5)
        assert report.hits == 1  # 关键词中，转述不中——FTS5 的真实脾气


class TestFormatReport:
    def test_report_layout(self) -> None:
        report = run_recall(CASES, fake_search({"命中": ["题A"], "命中2": ["题C"]}), k=5)
        text = format_report(report)
        assert "recall@5" in text
        assert "落空" in text  # 漏网清单里看得到哪条没中
