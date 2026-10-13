"""diagnose 技能：面试诊断的菜谱（教程 04-tools-skills）。

菜谱不替模型做决定——它只写导演剧本（system prompt）告诉模型三步流程，
然后启动 loop 让模型自主下单。模型是厨师，菜谱是参考，火候它自己掌握。
"""

from __future__ import annotations

from pathlib import Path

from offer_coach.engine.engine import QueryEngine
from offer_coach.engine.models import Message
from offer_coach.tools.builtin import default_registry
from offer_coach.tools.loop import run_loop

_DIRECTOR_SCRIPT = """你是一位资深技术面试官，正在为候选人做面试诊断。

你手头有三个工具，请按以下流程工作：
1. 用 analyze_content 分析候选人的回答质量（四个维度打分）
2. 根据分析中暴露的薄弱知识点，用 query_knowledge_base 查相关面试题对照（可以查多次）
3. 用 generate_report 把分析结果排版成最终诊断报告

完成后，直接输出报告全文作为你的最终回答。"""


def diagnose(
    transcript_path: Path,
    engine: QueryEngine,
    db_path: Path,
    *,
    max_iterations: int = 10,
) -> str:
    """诊断一份面试稿，返回报告文本。模型的账单在 engine.ledger 里。"""
    transcript = transcript_path.read_text(encoding="utf-8")
    registry = default_registry(engine, db_path)
    result = run_loop(
        engine,
        registry,
        [
            Message(role="system", content=_DIRECTOR_SCRIPT),
            Message(role="user", content=f"这是候选人的面试稿，请诊断：\n\n{transcript}"),
        ],
        max_iterations=max_iterations,
    )
    if result.status != "completed":
        raise RuntimeError(f"诊断未完成（{result.status}）：模型没有走完流程，请重试")
    return result.final_text or ""
