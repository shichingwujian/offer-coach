"""漏网解剖（P2-1）：recall@k 的"漏网"只是没进前 k，第 k+1 名和第 100 名是两种病。

对每条漏网，查标准答案在三个通道（拆词 / 向量 / 融合）完整榜单里的名次，
按名次把漏网归成三类病：

- **召回病（recall_gap）**：两个单通道的候选池前列都捞不到目标题——
  语义鸿沟太深或术语对不上，药方是补同义词 / 换更强 embedding。
- **融合挤压（fusion_squeeze）**：某个单通道明明前 k，融合后却掉出前 k——
  计分规则（RRF）冤枉了好通道，药方在融合层，不是换模型。
- **排序病（ranking）**：进得了候选池前列，但排不进前 k——
  粗排够到边了，药方是 reranker 精排或调权重。

全程字符串比对标题，零模型调用：答案卡（expect）是人手写的，
解剖器不需要"知道"哪题对，只需要在榜单里找它的名次。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from offer_coach.evaluation.recall import CaseResult
from offer_coach.knowledge.parser import Question

ChannelSearch = Callable[[str, int], list[Question]]  # (查询, 榜单长度) → 完整榜单

MissCause = Literal["recall_gap", "ranking", "fusion_squeeze"]

CAUSE_LABELS: dict[MissCause, str] = {
    "recall_gap": "召回病",
    "ranking": "排序病",
    "fusion_squeeze": "融合挤压",
}


class MissRank(BaseModel):
    """一条漏网的名次解剖：标准答案在三个通道各排第几（None = 没进该通道候选池）。"""

    query: str
    type: str
    expects: list[str]
    terms_rank: int | None
    vector_rank: int | None
    hybrid_rank: int | None
    cause: MissCause


def find_rank(hits: list[Question], expects: list[str]) -> int | None:
    """在榜单里找任一标准答案的最早名次（1 起）。找不到 = None（没进候选池）。"""
    for i, q in enumerate(hits, start=1):
        if q.title in expects:
            return i
    return None


def classify(
    terms_rank: int | None,
    vector_rank: int | None,
    hybrid_rank: int | None,
    *,
    k: int = 5,
    recall_threshold: int = 20,
) -> MissCause:
    """按名次归类病因。k = 评估截断线；recall_threshold = 候选池多深算"捞到过"。"""
    channel_ranks = [r for r in (terms_rank, vector_rank) if r is not None]
    best_channel = min(channel_ranks) if channel_ranks else None
    if (
        best_channel is not None
        and best_channel <= k
        and (hybrid_rank is None or hybrid_rank > k)
    ):
        return "fusion_squeeze"  # 单通道前 k、融合后掉出前 k：计分规则冤枉了好通道
    if best_channel is None or best_channel > recall_threshold:
        return "recall_gap"  # 两个通道候选池前列都捞不到：召回病
    return "ranking"  # 捞得到但排不进前 k：排序病


def dissect_misses(
    misses: list[CaseResult],
    *,
    terms_search: ChannelSearch,
    vector_search: ChannelSearch,
    hybrid_search: ChannelSearch,
    pool: int = 50,
    k: int = 5,
    recall_threshold: int = 20,
) -> list[MissRank]:
    """逐条解剖漏网：同一查询在三个通道各拉一份完整榜单，找标准答案的名次。"""
    results: list[MissRank] = []
    for miss in misses:
        case = miss.case
        terms_rank = find_rank(terms_search(case.query, pool), case.expect)
        vector_rank = find_rank(vector_search(case.query, pool), case.expect)
        hybrid_rank = find_rank(hybrid_search(case.query, pool), case.expect)
        results.append(
            MissRank(
                query=case.query,
                type=case.type,
                expects=case.expect,
                terms_rank=terms_rank,
                vector_rank=vector_rank,
                hybrid_rank=hybrid_rank,
                cause=classify(
                    terms_rank,
                    vector_rank,
                    hybrid_rank,
                    k=k,
                    recall_threshold=recall_threshold,
                ),
            )
        )
    return results


def format_dissection(ranks: list[MissRank], *, k: int = 5) -> str:
    """把解剖结果排成人看的文本：每条漏网的三通道名次 + 病因统计。"""
    def fmt(v: int | None) -> str:
        return "未进池" if v is None else str(v)

    lines = [f"漏网解剖（标准答案实际名次，k={k} 截断线）："]
    for r in ranks:
        lines.append(f"- [{r.type}] {r.query}")
        lines.append(
            f"  名次：拆词 {fmt(r.terms_rank)} / 向量 {fmt(r.vector_rank)}"
            f" / 融合 {fmt(r.hybrid_rank)} → {CAUSE_LABELS[r.cause]}"
        )
    counts = {c: sum(1 for r in ranks if r.cause == c) for c in CAUSE_LABELS}
    lines.append("")
    lines.append(
        "病因统计："
        + " / ".join(f"{CAUSE_LABELS[c]} {n} 条" for c, n in counts.items() if n)
    )
    return "\n".join(lines)
