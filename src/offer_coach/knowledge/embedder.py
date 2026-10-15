"""向量嵌入（D13）：把文字算成"语义坐标"，意思近的文字坐标近。

Embedder 是接口（Protocol）：真的（FastEmbedder，本地 bge 中文模型）和
假的（FakeEmbedder，测试用哈希造确定性假向量）可互换——DI 第 7 次。
真机零 API 依赖：DeepSeek/Kimi 都没有 embedding 接口，本地模型离线免费可复现（D010）。
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import Protocol


class Embedder(Protocol):
    """向量后端接口：文字列表进，向量列表出。真的假的都长这样。"""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedder:
    """真向量：fastembed + bge-small-zh（512 维）。首次使用自动下载模型（约 100MB）。

    懒加载：import 快，第一次 embed 才下载/加载模型——测试和 CI 永远不碰它。
    """

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5") -> None:
        self._model_name = model_name
        self._model = None  # 第一次 embed 时才加载

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            from fastembed import TextEmbedding  # 重依赖，只在真用时才 import

            self._model = TextEmbedding(model_name=self._model_name)
        return [list(map(float, v)) for v in self._model.embed(texts)]


class FakeEmbedder:
    """假向量：测试专用。哈希造确定性向量（同一文本永远同一向量），零依赖零联网。

    可用 mapping 指定"某文本 → 某向量"，让测试精确控制谁和谁相似。
    """

    def __init__(self, mapping: dict[str, list[float]] | None = None, dim: int = 8) -> None:
        self._mapping = mapping or {}
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._mapping.get(t) or self._hash_vec(t) for t in texts]

    def _hash_vec(self, text: str) -> list[float]:
        # sha256 当种子：跨进程稳定（内置 hash() 每次运行会变，不能用于测试）
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        rng = random.Random(seed)
        return [rng.uniform(-1, 1) for _ in range(self._dim)]


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度：只看两个向量指的方向像不像（1.0 同向 / 0 无关 / -1 相反），不看长短。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
