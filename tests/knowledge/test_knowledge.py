"""题库层测试：解析、灌库、检索、工具换内脏。

数据库全部建在 pytest 的 tmp_path（临时目录，测完自动删），不碰真实题库。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from offer_coach.knowledge import build_db, parse_markdown, search_questions
from offer_coach.engine import EngineConfig, FakeProvider, QueryEngine, RetryConfig
from offer_coach.tools import default_registry, make_query_knowledge_base

SAMPLE_MD = """---
layout: default
title: 测试分类
---

# 测试分类

开头介绍语，不是题目。

## 第一节

### Q：Redis 持久化机制有哪些？

RDB 快照和 AOF 日志，前者恢复快，后者更安全。

### Q：Python 的 GIL 是什么？

全局解释器锁，同一时刻只有一个线程执行字节码。

## 第二节

这一节没有题。
"""


def no_sleep(_seconds: float) -> None:
    """测试用 sleep：不真等。"""


@pytest.fixture
def kb_db(tmp_path: Path) -> Path:
    """临时题库：两道种子题，建在临时目录里。"""
    src = tmp_path / "bank"
    category = src / "01-test-category"
    category.mkdir(parents=True)
    (category / "index.md").write_text(SAMPLE_MD, encoding="utf-8")
    db = tmp_path / "questions.db"
    build_db(src, db)
    return db


class TestParser:
    def test_splits_questions_and_strips_frontmatter(self) -> None:
        questions = parse_markdown(SAMPLE_MD, "01-test-category")
        assert len(questions) == 2
        assert questions[0].title == "Redis 持久化机制有哪些？"
        assert questions[0].category == "01-test-category"
        assert "RDB" in questions[0].body
        assert "layout" not in questions[0].body  # frontmatter 被剥掉

    def test_body_stops_at_next_section(self) -> None:
        questions = parse_markdown(SAMPLE_MD, "cat")
        assert "第二节" not in questions[-1].body  # 下一节的内容不漏进上一题


class TestBuildAndSearch:
    def test_build_returns_count(self, tmp_path: Path, kb_db: Path) -> None:
        # fixture 已灌过一次：直接搜验证数量
        assert len(search_questions(kb_db, "Redis")) == 1
        assert len(search_questions(kb_db, "GIL")) == 1

    def test_build_is_idempotent(self, tmp_path: Path) -> None:
        src = tmp_path / "bank"
        cat = src / "01-cat"
        cat.mkdir(parents=True)
        (cat / "index.md").write_text(SAMPLE_MD, encoding="utf-8")
        db = tmp_path / "q.db"
        first = build_db(src, db)
        second = build_db(src, db)  # 跑两遍
        assert first == second == 2  # 题数不变（幂等）

    def test_chinese_keyword_search(self, kb_db: Path) -> None:
        hits = search_questions(kb_db, "持久化")
        assert len(hits) == 1 and "Redis" in hits[0].title  # trigram 中文检索生效

    def test_miss_returns_empty(self, kb_db: Path) -> None:
        assert search_questions(kb_db, "量子计算") == []

    def test_short_keyword_falls_back_to_like(self, kb_db: Path) -> None:
        # trigram 索引没有不足 3 字的词，"快照"只有 2 字 → 走 LIKE 兜底
        hits = search_questions(kb_db, "快照")
        assert len(hits) == 1 and "RDB" in hits[0].body

    def test_missing_db_raises_clear_error(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="ingest"):
            search_questions(tmp_path / "不存在.db", "Redis")


class TestToolSwap:
    """工具换内脏：种子题已删，查的是真库。说明书和签名不变。"""

    def test_query_tool_hits_real_db(self, kb_db: Path) -> None:
        query = make_query_knowledge_base(kb_db)
        result = query("Redis")
        assert "RDB" in result and "01-test-category" in result

    def test_query_tool_miss(self, kb_db: Path) -> None:
        assert "未找到" in make_query_knowledge_base(kb_db)("量子计算")

    def test_registry_wires_db(self, kb_db: Path) -> None:
        engine = QueryEngine(EngineConfig(
            provider=FakeProvider([]),
            retry=RetryConfig(base_delay=0.01),
            sleep=no_sleep,
        ))
        registry = default_registry(engine, kb_db)
        tool = registry.get("query_knowledge_base")
        assert tool is not None
        assert "RDB" in tool.func(keyword="Redis")
