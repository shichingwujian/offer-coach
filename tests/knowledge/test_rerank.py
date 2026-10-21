"""P2-3b 精排复评测试：FakeReranker 控制复评分数，验证两阶段管道本身。

真精排（bge-reranker-base）只在真机评估用；测试全走 FakeReranker，零联网。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from offer_coach.knowledge.db import search_hybrid
from offer_coach.knowledge.embedder import FakeEmbedder
from offer_coach.knowledge.parser import Question
from offer_coach.knowledge.reranker import FakeReranker


def q(title: str) -> Question:
    return Question(category="测试", title=title, body="x")


def rerank_text(title: str) -> str:
    """复评文本 = 标题 + 正文前 200 字（与 search_hybrid 内部构造一致）。"""
    return f"{title}\nx"


def stub_boards(
    monkeypatch: pytest.MonkeyPatch, lexical: list[Question], semantic: list[Question]
) -> None:
    """替换两个通道的榜单，让测试精确控制粗排名次。"""
    import offer_coach.knowledge.db as db_module

    monkeypatch.setattr(db_module, "search_smart", lambda _db, _q, limit=5: lexical[:limit])
    monkeypatch.setattr(
        db_module, "search_vectors", lambda _db, _q, limit=5, *, embedder: semantic[:limit]
    )


class TestFakeReranker:
    def test_mapping_controls_scores(self) -> None:
        r = FakeReranker({"题A": 9.5})
        assert r.score("查询", ["题A", "题B"]) == [9.5, 0.0]  # 未指定的一律 0

    def test_scores_align_with_input_order(self) -> None:
        r = FakeReranker({"题B": 1.0, "题C": 2.0})
        assert r.score("查询", ["题C", "题A", "题B"]) == [2.0, 0.0, 1.0]


class TestHybridRerank:
    """两阶段：RRF 粗排圈决赛圈 → 精排读原文重打分。"""

    def test_reranker_rescues_squeezed_target(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """融合挤压现场：字面第 1 的干扰王压过向量第 3 的目标；
        精排给目标打满分 → 目标反超到第一。"""
        target = q("目标题：内容其实最相关")
        king = q("字面干扰王")
        stub_boards(
            monkeypatch,
            lexical=[king] + [q(f"字面干扰{i}") for i in range(4)],
            semantic=[q(f"语义干扰{i}") for i in range(2)] + [target],
        )
        # 粗排：干扰王第一（1/61 > 1/63），融合挤压成立
        coarse = search_hybrid(tmp_path / "x.db", "查询", embedder=FakeEmbedder())
        assert coarse[0].title == king.title
        # 精排：只信内容不信名次，目标被捞回
        reranker = FakeReranker({rerank_text(target.title): 10.0})
        hits = search_hybrid(tmp_path / "x.db", "查询", embedder=FakeEmbedder(), reranker=reranker)
        assert hits[0].title == target.title

    def test_reranker_only_reviews_finals(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """精排只复评前 rerank_top 名：决赛圈外的题打满分也捞不回。"""
        target = q("目标题：融合第 8 名")
        lexical = [q(f"字面干扰{i}") for i in range(7)] + [target]
        stub_boards(monkeypatch, lexical=lexical, semantic=[])
        reranker = FakeReranker({rerank_text(target.title): 99.0})
        hits = search_hybrid(
            tmp_path / "x.db",
            "查询",
            limit=3,
            embedder=FakeEmbedder(),
            reranker=reranker,
            rerank_top=3,  # 决赛圈只放 3 个，第 8 名进不来
        )
        assert target.title not in [h.title for h in hits]

    def test_no_reranker_behavior_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """不给 reranker：输出与 P2-2 纯 RRF 完全一致（回归保险）。"""
        king = q("字面干扰王")
        stub_boards(
            monkeypatch,
            lexical=[king, q("字面干扰1")],
            semantic=[q("语义干扰0")],
        )
        hits = search_hybrid(tmp_path / "x.db", "查询", embedder=FakeEmbedder())
        assert hits[0].title == king.title  # 字面第 1 + RRF 一人一票，干扰王坐稳


class TestHybridBlend:
    """P2-3c 合议制：粗排分和复评分各自归一化到 [0,1]，按 α 加权合计。

    榜单布置：字面王第 1（粗排分最高）；目标题向量第 2（粗排分中等）；
    复评裁判只看好目标题（满分），其余 0 分。
    """

    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
        king = q("字面王")
        target = q("目标题")
        stub_boards(
            monkeypatch,
            lexical=[king, q("字面甲"), q("字面乙")],
            semantic=[q("语义甲"), target],
        )
        return king.title, target.title

    def test_alpha_zero_ignores_reranker(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """α=0：复评裁判说了不算，字面王坐稳第一。"""
        king, target = self._setup(monkeypatch)
        reranker = FakeReranker({rerank_text(target): 99.0})
        hits = search_hybrid(
            tmp_path / "x.db", "查询", embedder=FakeEmbedder(),
            reranker=reranker, rerank_alpha=0.0,
        )
        assert hits[0].title == king

    def test_alpha_one_follows_reranker(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """α=1：复评裁判独断，目标题第一。"""
        king, target = self._setup(monkeypatch)
        reranker = FakeReranker({rerank_text(target): 99.0})
        hits = search_hybrid(
            tmp_path / "x.db", "查询", embedder=FakeEmbedder(),
            reranker=reranker, rerank_alpha=1.0,
        )
        assert hits[0].title == target

    def test_blend_balances_two_judges(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """α 居中：复评满分 + 粗排中等 → 目标反超（α=0.5）；
        α 偏小：粗排高分兜底，字面王不让位（α=0.3）。"""
        king, target = self._setup(monkeypatch)
        reranker = FakeReranker({rerank_text(target): 10.0})
        blended = search_hybrid(
            tmp_path / "x.db", "查询", embedder=FakeEmbedder(),
            reranker=reranker, rerank_alpha=0.5,
        )
        assert blended[0].title == target
        coarse_heavy = search_hybrid(
            tmp_path / "x.db", "查询", embedder=FakeEmbedder(),
            reranker=reranker, rerank_alpha=0.3,
        )
        assert coarse_heavy[0].title == king
