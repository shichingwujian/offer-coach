"""精排复评（P2-3b）：cross-encoder 读"查询+题目"原文，逐对打相关度分数。

Reranker 是接口（Protocol）：真的（FastReranker，本地 bge-reranker-base）和
假的（FakeReranker，测试用指定分数）可互换——DI 第 8 次。
粗排（字面/向量，快而糙）海选、精排（cross-encoder，慢而准）复评决赛圈：
两阶段分工。加权 RRF 已被评估集否决（D017：救挤压必砸 keyword），
reranker 不依赖通道名次，直接读内容打分。
"""

from __future__ import annotations

from typing import Protocol


class Reranker(Protocol):
    """精排接口：查询 + 文本列表进，相关度分数列表出（越高越相关）。"""

    def score(self, query: str, texts: list[str]) -> list[float]: ...


class FastReranker:
    """真精排：fastembed TextCrossEncoder，默认 bge-reranker-v2-m3（约 570MB）。

    懒加载：import 快，第一次 score 才下载/加载模型——测试和 CI 永远不碰它。
    与 Embedder 一样本地离线，DeepSeek/Kimi 没有 rerank 接口（D010 的延伸）。
    默认 v2-m3 是评估集扫出来的（D017）：base 独断 85.2% 打平基线，
    v2-m3 独断 92.6% 全场最高；裁判够强时合议制反而是负优化。
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3") -> None:
        self._model_name = model_name
        self._model = None  # 第一次 score 时才加载

    def score(self, query: str, texts: list[str]) -> list[float]:
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder  # 重依赖，真用才 import

            self._model = TextCrossEncoder(model_name=self._model_name)
        return [float(s) for s in self._model.rerank(query, texts)]


class FakeReranker:
    """假精排：测试专用。mapping 指定"文本 → 分数"，未指定的给 0.0。

    让测试精确控制"复评裁判看好谁"，零依赖零联网。
    """

    def __init__(self, mapping: dict[str, float] | None = None) -> None:
        self._mapping = mapping or {}

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [self._mapping.get(t, 0.0) for t in texts]
