"""D12 查询预处理测试：拆词三刀（extract_terms）+ 拆词检索合并（search_smart）。

拆词逻辑是纯函数，直接测死；合并排序用真灌的小题库走端到端。
"""

from __future__ import annotations

from pathlib import Path

from offer_coach.knowledge.db import build_db, search_questions, search_smart
from offer_coach.knowledge.preprocess import extract_terms


class TestExtractTerms:
    def test_stopwords_cut_paraphrase(self) -> None:
        terms = extract_terms("把文本变成向量是干嘛的")
        assert "文本变成向量" in terms  # 整段也留：短语命中是最强信号
        assert "文本" in terms and "变成" in terms and "向量" in terms
        assert "干嘛" not in terms  # 废话词已扔

    def test_scenario_wrapper_removed(self) -> None:
        terms = extract_terms("面试官问我 MCP 到底解决了什么问题")
        assert "MCP" in terms
        assert "解决" in terms
        assert not any("面试官" in t for t in terms)

    def test_short_chunk_kept_whole(self) -> None:
        assert extract_terms("死锁") == ["死锁"]

    def test_latin_term_not_windowed(self) -> None:
        # 英文技术词是原子的，滑窗只会切出噪音
        assert extract_terms("IVF_FLAT") == ["IVF_FLAT"]

    def test_cjk_long_chunk_sliding_bigrams(self) -> None:
        terms = extract_terms("文本变成向量")
        assert terms == ["文本变成向量", "文本", "本变", "变成", "成向", "向量"]

    def test_all_stopwords_returns_empty(self) -> None:
        assert extract_terms("是什么呢") == []

    def test_dedup_keeps_order(self) -> None:
        terms = extract_terms("向量，向量数据库")
        assert terms.count("向量") == 1
        assert terms[0] == "向量"  # 先出现的先收


def _build_tiny_bank(tmp_path: Path) -> Path:
    src = tmp_path / "bank"
    (src / "01-vdb").mkdir(parents=True)
    (src / "01-vdb" / "index.md").write_text(
        "### Q：什么是 embedding？\n\n把文本变成向量，方便计算语义相似度。\n\n"
        "### Q：什么是余弦相似度？\n\n衡量两个向量的夹角。\n\n"
        "### Q：什么是分布式锁？\n\n跨进程互斥，Redis 可实现。\n\n"
        "### Q：Redis 持久化方式有哪些？\n\nRDB 快照和 AOF 日志。\n",
        encoding="utf-8",
    )
    db = tmp_path / "q.db"
    build_db(src, db)
    return db


class TestSearchSmart:
    def test_paraphrase_breaks_zero(self, tmp_path: Path) -> None:
        """同一个口语查询：基线空手而归，拆词后命中——D12 的存在意义。"""
        db = _build_tiny_bank(tmp_path)
        query = "把文本变成向量是干嘛的"
        assert search_questions(db, query) == []  # 基线：整句短语匹配无结果
        hits = search_smart(db, query)
        assert hits[0].title == "什么是 embedding？"

    def test_keyword_still_hits(self, tmp_path: Path) -> None:
        """keyword 型不能回退：拆词后依然命中且排第一。"""
        db = _build_tiny_bank(tmp_path)
        hits = search_smart(db, "余弦相似度")
        assert hits[0].title == "什么是余弦相似度？"

    def test_multi_term_hit_ranks_first(self, tmp_path: Path) -> None:
        """命中词数多的排前面：两个词都中的题 > 只中一个词的题。"""
        db = _build_tiny_bank(tmp_path)
        hits = search_smart(db, "分布式锁 Redis 怎么实现")
        titles = [q.title for q in hits]
        assert titles[0] == "什么是分布式锁？"  # 分布式锁+Redis 双命中
        assert "Redis 持久化方式有哪些？" in titles  # 只中 Redis，排后面

    def test_all_stopwords_returns_empty(self, tmp_path: Path) -> None:
        db = _build_tiny_bank(tmp_path)
        assert search_smart(db, "是什么呢") == []
