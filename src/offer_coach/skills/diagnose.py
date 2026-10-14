"""diagnose 技能：面试诊断的菜谱（教程 04-tools-skills）。

菜谱不替模型做决定——它只写导演剧本（system prompt）告诉模型三步流程，
然后启动 loop 让模型自主下单。模型是厨师，菜谱是参考，火候它自己掌握。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from offer_coach.context.manager import ContextManager
from offer_coach.engine.engine import QueryEngine
from offer_coach.engine.models import Message
from offer_coach.hooks.pipeline import HookPipeline, truncate_hook
from offer_coach.memory import MemoryStore, make_memory_hook, recall_block
from offer_coach.permission.gate import PermissionGate
from offer_coach.session import load_session, save_session
from offer_coach.tools.builtin import default_registry
from offer_coach.tools.loop import run_loop

_DIRECTOR_SCRIPT = """你是一位资深技术面试官，正在为候选人做面试诊断。

你手头有三个工具，请按以下流程工作：
1. 用 analyze_content 分析候选人的回答质量（四个维度打分）
2. 根据分析中暴露的薄弱知识点，用 query_knowledge_base 查相关面试题对照（可以查多次）
3. 用 generate_report 把分析结果排版成最终诊断报告

完成后，直接输出报告全文作为你的最终回答。"""

# D10：开局召回的历史档案拼进剧本——模型开局就知道"这个人以前弱在哪"
_MEMORY_WRAP = """

这位候选人的历史档案（跨会话记忆）：
{block}
请在诊断中结合历史：老弱点是否改善、哪些维度反复出问题。"""


def diagnose(
    transcript_path: Path,
    engine: QueryEngine,
    db_path: Path,
    *,
    max_iterations: int = 10,
    gate: PermissionGate | None = None,  # 可选：权限闸门（D8）
    session_path: Path | None = None,  # 可选：跑完把历史存到这个档案（D8）
    resume: bool = False,  # True 时忽略稿子，从 session_path 读档续跑
    memory: MemoryStore | None = None,  # 可选：档案柜（D10）。传了就开局召回 + 跑完记档
) -> str:
    """诊断一份面试稿，返回报告文本。模型的账单在 engine.ledger 里。"""
    if resume and session_path is not None:
        messages = load_session(session_path)  # 读档：接着上次的历史继续
    else:
        transcript = transcript_path.read_text(encoding="utf-8")
        script = _DIRECTOR_SCRIPT
        if memory is not None:
            block = recall_block(memory)  # 开局召回：抽几份档案摆上桌
            if block:
                script += _MEMORY_WRAP.format(block=block)
        messages = [
            Message(role="system", content=script),
            Message(role="user", content=f"这是候选人的面试稿，请诊断：\n\n{transcript}"),
        ]
    registry = default_registry(engine, db_path)
    # 插线板装配（D9）：权限闸插 pre 孔；档案员和结果压缩插 post 孔（D10）
    # 顺序有意义：档案员先看完整原文，截断殿后只影响喂给模型的副本
    pipeline = HookPipeline()
    if gate is not None:
        pipeline.add_pre(gate.as_hook())
    if memory is not None:
        pipeline.add_post(make_memory_hook(memory))
    pipeline.add_post(truncate_hook(2000))
    result = run_loop(
        engine,
        registry,
        messages,
        max_iterations=max_iterations,
        context=ContextManager(),  # D7：桌面管理，防多轮诊断历史膨胀
        hooks=pipeline,
    )
    if session_path is not None:
        save_session(session_path, result.messages)  # 存档：中断也能续跑
    if result.status != "completed":
        raise RuntimeError(f"诊断未完成（{result.status}）：模型没有走完流程，请重试")
    if memory is not None:
        _write_summary(memory, transcript_path, result.final_text or "")  # 跑成才记档
    return result.final_text or ""


def _write_summary(store: MemoryStore, transcript_path: Path, report: str) -> None:
    """诊断收尾：写一条摘要 + 画像计数 +1。克制原则：只记关键数据点，不记全文。"""
    profile = store.get_profile()
    total = profile.get("total_diagnoses", 0) + 1
    today = date.today().isoformat()
    store.update_profile({"total_diagnoses": total, "last_diagnosis_date": today})
    store.create("diagnosis_summary", f"diag-{today}-{total}", {
        "date": today,
        "transcript": transcript_path.name,
        "weak_dimensions": store.get_profile().get("weak_dimensions", []),
        "report_excerpt": report[:120],
    })
