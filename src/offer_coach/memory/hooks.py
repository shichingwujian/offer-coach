"""记忆写入插件：盯 analyze_content 的评分结果，低分维度自动记入档案（教程 06 后半）。

死规则（写入克制原则，不让模型自由发挥）：
1. 只有 analyze_content 的结果触发记忆——别的工具看都不看
2. 只有低分维度（< 3/5）记为弱点；解析不到分数就宁可不记

同一维度再考砸：不新增条目，给老条目坐实度 +0.1（封顶 1.0）——
"一次考砸是意外，次次考砸才是弱项"。
"""

from __future__ import annotations

import re

from offer_coach.hooks.pipeline import PostToolHook
from offer_coach.memory.store import MemoryStore
from offer_coach.tools.builtin import DIMENSIONS

# 记忆插件靠 analyze 渲染的固定格式（"技术准确性：2/5"）解析分数
_SCORE_PATTERN = {dim: re.compile(rf"{dim}[：:]\s*(\d)\s*/\s*5") for dim in DIMENSIONS}


def make_memory_hook(store: MemoryStore, *, low_threshold: int = 3) -> PostToolHook:
    """造一个"档案员"插件：旁观 analyze 结果，低分维度记弱点 + 更新画像。

    旁观型插件：永不改写结果（原样返回），只往档案柜里写——
    post 孔不止能"装盘"，也能"留痕"。
    """

    def memory_hook(tool_name: str, _arguments: str, result: str) -> str:
        if tool_name != "analyze_content":
            return result
        scores = {
            dim: int(m.group(1))
            for dim, pattern in _SCORE_PATTERN.items()
            if (m := pattern.search(result))
        }
        if not scores:
            return result  # 解析不到分数：宁可漏记，不可错记
        weak = [dim for dim, score in scores.items() if score < low_threshold]
        for dim in weak:
            existing = store.retrieve(type="weak_point", key=dim)
            if existing:
                store.update(existing[0].id, {"dimension": dim, "score": scores[dim]}, boost=True)
            else:
                store.create("weak_point", dim, {"dimension": dim, "score": scores[dim]})
        # 画像更新：本轮分数 + 弱项维度（保留最近 5 个）
        profile = store.get_profile()
        dims = list(dict.fromkeys([*profile.get("weak_dimensions", []), *weak]))[-5:]
        store.update_profile({"last_scores": scores, "weak_dimensions": dims})
        return result

    return memory_hook
