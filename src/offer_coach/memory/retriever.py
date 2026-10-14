"""开局召回：每次诊断/对话开始，从档案柜抽几份最相关的摆上桌面（教程 06 后半）。

不整柜搬——D7 的教训：桌面预算有限。抽法是死规则：
画像（非空字段）+ 坐实度 ≥ 0.6 的弱点（最多 5 条）+ 最近 2 次诊断摘要。
坐实度 0.5 的新弱点不上桌面——一次考砸是意外，先观望。
"""

from __future__ import annotations

from offer_coach.memory.store import MemoryStore


def recall_block(store: MemoryStore) -> str:
    """拼一段注入 system prompt 的"历史档案"文本。柜子是空的就返回空串。"""
    parts: list[str] = []
    profile = store.get_profile()
    if role := profile.get("target_role"):
        parts.append(f"目标岗位：{role}")
    if stack := profile.get("tech_stack"):
        parts.append(f"技术栈：{'、'.join(stack)}")
    if n := profile.get("total_diagnoses"):
        parts.append(f"累计诊断：{n} 次")
    if dims := profile.get("weak_dimensions"):
        parts.append(f"历史弱项维度：{'、'.join(dims)}")
    weaks = store.retrieve(type="weak_point", min_confidence=0.6, limit=5)
    if weaks:
        parts.append("坐实的薄弱点：")
        parts.extend(
            f"- {w.key}（最近 {w.value.get('score', '?')}/5，坐实度 {w.confidence:.1f}）"
            for w in weaks
        )
    summaries = store.retrieve(type="diagnosis_summary", limit=2)
    if summaries:
        parts.append("最近诊断：")
        parts.extend(
            f"- {s.value.get('date', '?')}：弱项 {'、'.join(s.value.get('weak_dimensions', [])) or '无'}"
            for s in summaries
        )
    return "\n".join(parts)
