"""D13 混合召回测试：FakeEmbedder 造确定性假向量，真模型只在真机验收用。

测试目标不是"语义像不像"（那是真模型的活），而是管道本身：
向量存取、余弦排序、RRF 融合、没建向量表时的静默退化。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from offer_coach.knowledge.db import (
    build_db,
    build_vectors,
    search_for_diagnosis,
    search_hybrid,
    search_smart,
    search_vectors,
)
from offer_coach.knowledge.embedder import FakeEmbedder, cosine


class TestCosine:
    def test_same_direction_is_one(self) -> None:
        assert cosine([1.0, 2.0], [2.0, 4.0]) == pytest.approx(1.0)  # 方向一致，长短不影响

    def test_orthogonal_is_zero(self) -> None:
        assert abs(cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_zero_vector_is_safe(self) -> None:
        assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0  # 不炸，返回 0


class TestFakeEmbedder:
    def test_deterministic(self) -> None:
        e = FakeEmbedder()
        assert e.embed(["余弦相似度"]) == e.embed(["余弦相似度"])  # 同一文本永远同一向量

    def test_mapping_overrides_hash(self) -> None:
        e = FakeEmbedder({"A": [1.0, 0.0], "B": [1.0, 0.0]}, dim=2)
        a, b = e.embed(["A", "B"])
        assert cosine(a, b) == 1.0  # mapping 让测试精确控制"谁和谁像"


_LOCK_TITLE = "什么是分布式锁？"
# 正文刻意不含查询词（跨进程互斥怎么搞）的任何二字以上片段——真·字面零重叠
_LOCK_BODY = "Redis 可实现，SETNX 语义。"
_LOCK_TEXT = f"{_LOCK_TITLE}\n{_LOCK_BODY}"  # build_vectors 的向量文本 = 标题 + 正文前 200 字


def _build_bank_with_vecs(tmp_path: Path, embedder: FakeEmbedder) -> Path:
    src = tmp_path / "bank"
    (src / "01-t").mkdir(parents=True)
    (src / "01-t" / "index.md").write_text(
        f"### Q：{_LOCK_TITLE}\n\n{_LOCK_BODY}\n\n"
        "### Q：Redis 持久化方式有哪些？\n\nRDB 快照和 AOF 日志。\n\n"
        "### Q：什么是余弦相似度？\n\n衡量两个向量的夹角。\n",
        encoding="utf-8",
    )
    db = tmp_path / "q.db"
    build_db(src, db)
    build_vectors(db, embedder)
    return db


class TestSearchVectors:
    def test_semantic_ranking(self, tmp_path: Path) -> None:
        """查询向量和目标题向量同向 → 目标题排第一（模拟"语义相近"）。"""
        e = FakeEmbedder({"跨进程互斥怎么搞": [1.0, 0.0], _LOCK_TEXT: [1.0, 0.0]}, dim=2)
        db = _build_bank_with_vecs(tmp_path, e)
        hits = search_vectors(db, "跨进程互斥怎么搞", embedder=e)
        assert hits[0].title == _LOCK_TITLE  # 字面零重叠，靠坐标近命中

    def test_no_vector_table_degrades_silently(self, tmp_path: Path) -> None:
        """没跑过 build_vectors 的库：语义通道没货，返回空而不是报错。"""
        src = tmp_path / "bank"
        (src / "01-t").mkdir(parents=True)
        (src / "01-t" / "index.md").write_text("### Q：题？\n\n答。\n", encoding="utf-8")
        db = tmp_path / "q.db"
        build_db(src, db)
        assert search_vectors(db, "随便", embedder=FakeEmbedder()) == []


class TestSearchHybrid:
    def test_rrf_fusion_lets_semantic_only_surface(self, tmp_path: Path) -> None:
        """字面榜查不到的题，语义榜靠前也能进最终结果——混合召回的存在意义。"""
        e = FakeEmbedder({"跨进程互斥怎么搞": [1.0, 0.0], _LOCK_TEXT: [1.0, 0.0]}, dim=2)
        db = _build_bank_with_vecs(tmp_path, e)
        query = "跨进程互斥怎么搞"
        # 字面通道：查询与题库零字面重叠 → 拆词也查不到分布式锁
        assert all(_LOCK_TITLE != q.title for q in search_smart(db, query))
        # 混合通道：语义榜把它顶进来
        hits = search_hybrid(db, query, embedder=e)
        assert hits[0].title == _LOCK_TITLE

    def test_lexical_still_works_without_vectors(self, tmp_path: Path) -> None:
        """没建向量表时，混合召回退化成纯字面，不报错。"""
        src = tmp_path / "bank"
        (src / "01-t").mkdir(parents=True)
        (src / "01-t" / "index.md").write_text(
            "### Q：什么是余弦相似度？\n\n衡量向量夹角。\n", encoding="utf-8"
        )
        db = tmp_path / "q.db"
        build_db(src, db)
        hits = search_hybrid(db, "余弦相似度", embedder=FakeEmbedder())
        assert hits[0].title == "什么是余弦相似度？"

    def test_both_boards_hit_ranks_higher(self, tmp_path: Path) -> None:
        """RRF 特性：两榜都中的题 > 只中一榜的题。"""
        e = FakeEmbedder({"分布式锁": [1.0, 0.0], _LOCK_TEXT: [1.0, 0.0]}, dim=2)
        db = _build_bank_with_vecs(tmp_path, e)
        hits = search_hybrid(db, "分布式锁", embedder=e)
        # 分布式锁题：字面榜有（标题含词）+ 语义榜第一 → 必须排第一
        assert hits[0].title == _LOCK_TITLE


class TestSearchForDiagnosis:
    """正式诊断入口：请求模式和真实使用模式分开，fallback 必须留痕。"""

    def test_auto_uses_hybrid_when_vectors_available(self, tmp_path: Path) -> None:
        e = FakeEmbedder({"跨进程互斥怎么搞": [1.0, 0.0], _LOCK_TEXT: [1.0, 0.0]}, dim=2)
        db = _build_bank_with_vecs(tmp_path, e)

        result = search_for_diagnosis(db, "跨进程互斥怎么搞", embedder=e)

        assert result.mode_used == "hybrid"
        assert result.fallback_reason is None
        assert result.hits[0].title == _LOCK_TITLE

    def test_auto_falls_back_to_terms_without_embedder(self, tmp_path: Path) -> None:
        e = FakeEmbedder()
        db = _build_bank_with_vecs(tmp_path, e)

        result = search_for_diagnosis(db, "分布式锁")

        assert result.mode_used == "terms"
        assert result.fallback_reason == "未提供向量模型"
        assert result.hits[0].title == _LOCK_TITLE

    def test_auto_falls_back_to_terms_without_vector_table(self, tmp_path: Path) -> None:
        src = tmp_path / "bank"
        (src / "01-t").mkdir(parents=True)
        (src / "01-t" / "index.md").write_text(
            "### Q：什么是余弦相似度？\n\n衡量向量夹角。\n", encoding="utf-8"
        )
        db = tmp_path / "q.db"
        build_db(src, db)

        result = search_for_diagnosis(db, "余弦相似度", embedder=FakeEmbedder())

        assert result.mode_used == "terms"
        assert result.fallback_reason == "未建向量索引"
        assert result.hits[0].title == "什么是余弦相似度？"

    def test_explicit_modes_report_their_real_channel(self, tmp_path: Path) -> None:
        e = FakeEmbedder({"分布式锁": [1.0, 0.0], _LOCK_TEXT: [1.0, 0.0]}, dim=2)
        db = _build_bank_with_vecs(tmp_path, e)

        phrase = search_for_diagnosis(db, "分布式锁", mode="phrase", embedder=e)
        terms = search_for_diagnosis(db, "分布式锁", mode="terms", embedder=e)
        hybrid = search_for_diagnosis(db, "分布式锁", mode="hybrid", embedder=e)

        assert phrase.mode_used == "phrase"
        assert terms.mode_used == "terms"
        assert hybrid.mode_used == "hybrid"
        assert hybrid.fallback_reason is None
