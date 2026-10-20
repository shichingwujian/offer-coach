"""漏网解剖（P2-1）测试：find_rank / classify / dissect_misses / format_dissection。

全是内存里的桩榜单，零数据库、零模型——解剖器只做字符串比对和名次归类。
"""

from offer_coach.evaluation import (
    CaseResult,
    EvalCase,
    classify,
    dissect_misses,
    find_rank,
    format_dissection,
)
from offer_coach.knowledge.parser import Question


def q(title: str) -> Question:
    return Question(category="测试", title=title, body="正文")


def board(*titles: str):
    """造一份榜单：按给定名次排好的题目列表。"""
    return [q(t) for t in titles]


def miss(query: str, expects: list[str], type: str = "paraphrase") -> CaseResult:
    return CaseResult(case=EvalCase(query=query, type=type, expect=expects), hit=False, got=[])


class TestFindRank:
    def test_found_returns_1_based_rank(self) -> None:
        hits = board("题A", "题B", "题C")
        assert find_rank(hits, ["题B"]) == 2

    def test_multi_expect_takes_earliest(self) -> None:
        hits = board("题A", "题B", "题C")
        assert find_rank(hits, ["题C", "题A"]) == 1  # 多答案，谁靠前算谁

    def test_not_in_pool_returns_none(self) -> None:
        hits = board("题A", "题B")
        assert find_rank(hits, ["八竿子打不着的题"]) is None

    def test_empty_board_returns_none(self) -> None:
        assert find_rank([], ["题A"]) is None


class TestClassify:
    def test_single_channel_topk_but_fused_out_is_fusion_squeeze(self) -> None:
        # 向量通道第 3，融合后第 8：计分规则冤枉了好通道
        assert classify(None, 3, 8) == "fusion_squeeze"

    def test_terms_topk_but_fused_out_is_also_fusion_squeeze(self) -> None:
        assert classify(4, None, None) == "fusion_squeeze"

    def test_in_pool_but_beyond_k_is_ranking(self) -> None:
        # 候选池捞得到（第 12 名），但排不进前 5
        assert classify(None, 12, 12) == "ranking"

    def test_beyond_threshold_is_recall_gap(self) -> None:
        assert classify(30, 25, 40) == "recall_gap"

    def test_all_channels_missing_is_recall_gap(self) -> None:
        assert classify(None, None, None) == "recall_gap"

    def test_threshold_boundary_is_ranking(self) -> None:
        # 刚好第 20 名：算捞到过，归排序病
        assert classify(None, 20, 20) == "ranking"


class TestDissectMisses:
    def test_collects_ranks_from_three_channels(self) -> None:
        misses = [miss("查询1", ["目标题"])]
        ranks = dissect_misses(
            misses,
            terms_search=lambda _q, _n: board("别的", "目标题"),      # 拆词第 2
            vector_search=lambda _q, _n: board("目标题"),            # 向量第 1
            hybrid_search=lambda _q, _n: board(*[f"别{i}" for i in range(8)]),  # 融合没进池
        )
        assert len(ranks) == 1
        r = ranks[0]
        assert r.terms_rank == 2
        assert r.vector_rank == 1
        assert r.hybrid_rank is None
        assert r.cause == "fusion_squeeze"  # 单通道前 5、融合掉出 → 融合挤压

    def test_query_and_expects_carried_over(self) -> None:
        misses = [miss("怎么再排一次", ["答案甲", "答案乙"], type="scenario")]
        ranks = dissect_misses(
            misses,
            terms_search=lambda _q, _n: [],
            vector_search=lambda _q, _n: [],
            hybrid_search=lambda _q, _n: [],
        )
        assert ranks[0].query == "怎么再排一次"
        assert ranks[0].type == "scenario"
        assert ranks[0].expects == ["答案甲", "答案乙"]
        assert ranks[0].cause == "recall_gap"


class TestFormatDissection:
    def test_output_shows_ranks_cause_and_summary(self) -> None:
        misses = [
            miss("查询A", ["目标A"]),
            miss("查询B", ["目标B"]),
        ]
        ranks = dissect_misses(
            misses,
            terms_search=lambda _q, _n: [],
            vector_search=lambda q_, _n: board("目标A") if q_ == "查询A" else [],
            hybrid_search=lambda _q, _n: [],
        )
        text = format_dissection(ranks)
        assert "查询A" in text and "向量 1" in text
        assert "查询B" in text and "未进池" in text
        assert "融合挤压 1 条" in text
        assert "召回病 1 条" in text
