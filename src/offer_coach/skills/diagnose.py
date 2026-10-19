"""diagnose 技能：面试诊断的菜谱（教程 04-tools-skills）。

菜谱不替模型做决定——它只写导演剧本（system prompt）告诉模型三步流程，
然后启动 loop 让模型自主下单。模型是厨师，菜谱是参考，火候它自己掌握。

P0-3：诊断结果显式分为 full / degraded / failed。降级报告只拼已有工具回执，
不再调用模型补写，避免把缺失步骤编造成完整结论。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from offer_coach.context.manager import ContextManager
from offer_coach.engine.engine import QueryEngine
from offer_coach.engine.errors import QueryEngineError
from offer_coach.engine.models import Message
from offer_coach.hooks.pipeline import HookPipeline, truncate_hook
from offer_coach.memory import MemoryStore, make_memory_hook, recall_block
from offer_coach.permission.gate import PermissionGate
from offer_coach.session import load_session, save_session
from offer_coach.tools.builtin import default_registry
from offer_coach.tools.loop import LoopResult, LoopStatus, ToolBudget, TurnTrace, run_loop

DiagnosisStatus = Literal["full", "degraded", "failed"]


class DiagnosisResult(BaseModel):
    """一次诊断的最终口径；report 只是产物，status 才决定能不能算成功。"""

    status: DiagnosisStatus
    report: str
    reason: str | None
    iterations: int | None  # loop 没正常返回时为 None
    loop_status: LoopStatus | None  # API 异常时为 None


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

# D14 消融对照组 no-script：只剩身份，没有流程——测"导演剧本"这层机制值多少
_BARE_SCRIPT = "你是一位资深技术面试官。请阅读候选人的面试稿，评估其回答质量，并给出你的诊断。"

# D14 消融对照组 no-kb：剧本改成两步，不提检索——测"题库弹药"这层机制值多少
_SCRIPT_NO_KB = """你是一位资深技术面试官，正在为候选人做面试诊断。

你手头有两个工具，请按以下流程工作：
1. 用 analyze_content 分析候选人的回答质量（四个维度打分）
2. 用 generate_report 把分析结果排版成最终诊断报告

完成后，直接输出报告全文作为你的最终回答。"""


def diagnose(
    transcript_path: Path,
    engine: QueryEngine,
    db_path: Path,
    *,
    max_iterations: int = 10,
    max_tool_calls: int | None = 8,
    max_kb_calls: int | None = 3,
    gate: PermissionGate | None = None,
    session_path: Path | None = None,
    resume: bool = False,
    memory: MemoryStore | None = None,
    ablate_kb: bool = False,
    ablate_script: bool = False,
) -> str:
    """严格入口：只有 full 才返回报告；degraded/failed 继续报错。

    保留这个口径是为了防止旧评估链路把"返回了一段降级文本"误算成完整成功。
    新调用方需要状态时请使用 diagnose_run()。
    """
    result = diagnose_run(
        transcript_path,
        engine,
        db_path,
        max_iterations=max_iterations,
        max_tool_calls=max_tool_calls,
        max_kb_calls=max_kb_calls,
        gate=gate,
        session_path=session_path,
        resume=resume,
        memory=memory,
        ablate_kb=ablate_kb,
        ablate_script=ablate_script,
    )
    if result.status == "full":
        return result.report
    raise RuntimeError(
        f"诊断未完成（{result.status}）：{result.reason}\n\n{result.report}"
    )


def diagnose_run(
    transcript_path: Path,
    engine: QueryEngine,
    db_path: Path,
    *,
    max_iterations: int = 10,
    max_tool_calls: int | None = 8,  # P0-2 总工具声明预算：正常三步流程只用 3 次
    max_kb_calls: int | None = 3,  # P0-2 单项检索预算：防长稿里反复查询题库
    gate: PermissionGate | None = None,  # 可选：权限闸门（D8）
    session_path: Path | None = None,  # 可选：跑完把历史存到这个档案（D8）
    resume: bool = False,  # True 时忽略稿子，从 session_path 读档续跑
    memory: MemoryStore | None = None,  # 可选：档案柜（D10）。传了就开局召回 + 跑完记档
    ablate_kb: bool = False,  # D14 消融对照组：没收题库工具（剧本同步改两步）
    ablate_script: bool = False,  # D14 消融对照组：摘掉导演剧本（只留身份）
) -> DiagnosisResult:
    """诊断一份面试稿，返回 full / degraded / failed 的结构化结果。"""
    if resume and session_path is not None:
        messages = load_session(session_path)  # 读档：接着上次的历史继续
    else:
        transcript = transcript_path.read_text(encoding="utf-8")
        if ablate_script:
            script = _BARE_SCRIPT
        elif ablate_kb:
            script = _SCRIPT_NO_KB
        else:
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
    if ablate_kb:
        registry.unregister("query_knowledge_base")  # 消融：没收检索工具
    # 插线板装配（D9）：权限闸插 pre 孔；档案员和结果压缩插 post 孔（D10）
    # 顺序有意义：档案员先看完整原文，截断殿后只影响喂给模型的副本
    pipeline = HookPipeline()
    if gate is not None:
        pipeline.add_pre(gate.as_hook())
    if memory is not None:
        pipeline.add_post(make_memory_hook(memory))
    pipeline.add_post(truncate_hook(2000))

    try:
        result = run_loop(
            engine,
            registry,
            messages,
            max_iterations=max_iterations,
            context=ContextManager(),  # D7：桌面管理，防多轮诊断历史膨胀
            hooks=pipeline,
            budget=ToolBudget(
                max_total_calls=max_tool_calls,
                max_calls_by_tool={"query_knowledge_base": max_kb_calls} if max_kb_calls is not None else {},
            ),
        )
    except QueryEngineError as e:
        reason = f"模型服务调用失败（{e.category}）：{e}"
        return DiagnosisResult(
            status="failed",
            report=_build_failed_report(reason),
            reason=reason,
            iterations=None,
            loop_status=None,
        )

    if session_path is not None:
        save_session(session_path, result.messages)  # 存档：中断也能续跑

    final_text = (result.final_text or "").strip()
    if result.status == "completed" and final_text:
        if memory is not None:
            _write_summary(memory, transcript_path, result.final_text or "")  # 完整跑成才记摘要
        return DiagnosisResult(
            status="full",
            report=result.final_text or "",
            reason=None,
            iterations=result.iterations,
            loop_status=result.status,
        )

    reason = _interruption_reason(result)
    materials = _successful_tool_materials(result)
    if materials:
        return DiagnosisResult(
            status="degraded",
            report=_build_degraded_report(reason, result, materials),
            reason=reason,
            iterations=result.iterations,
            loop_status=result.status,
        )
    return DiagnosisResult(
        status="failed",
        report=_build_failed_report(reason, result),
        reason=reason,
        iterations=result.iterations,
        loop_status=result.status,
    )


def _interruption_reason(result: LoopResult) -> str:
    """把 loop 状态翻译成诊断层能展示的原因。"""
    if result.status == "completed":
        return "模型正常结束，但没有返回报告正文"
    return f"诊断循环未完成（{result.status}，{result.iterations} 轮）"


def _successful_tool_materials(result: LoopResult) -> list[tuple[str, str]]:
    """找出成功且非空的工具回执；trace 负责定位，history 负责提供正文。"""
    success_names = {
        call.call_id: call.name
        for turn in result.trace
        for call in turn.tool_traces
        if call.outcome == "success" and call.result_chars > 0
    }
    materials = []
    for message in result.messages:
        if message.role != "tool" or message.tool_call_id not in success_names:
            continue
        content = (message.content or "").strip()
        if content:
            materials.append((success_names[message.tool_call_id], content))
    return materials


def _build_degraded_report(
    reason: str,
    result: LoopResult,
    materials: list[tuple[str, str]],
) -> str:
    """确定性拼接不完整报告：只展示事实材料，不调用模型补写。"""
    lines = [
        "# 面试诊断报告（不完整）",
        "",
        "> **状态：degraded**",
        f"> **原因**：{reason}",
        "",
    ]
    reports = [content for name, content in materials if name == "generate_report"]
    if reports:
        lines += ["## 已生成的报告草稿", "", reports[-1], ""]
    else:
        analyses = [content for name, content in materials if name == "analyze_content"]
        queries = [content for name, content in materials if name == "query_knowledge_base"]
        others = [
            (name, content)
            for name, content in materials
            if name not in {"analyze_content", "query_knowledge_base", "generate_report"}
        ]
        if analyses:
            lines += ["## 已完成的分析", "", analyses[-1], ""]
        if queries:
            lines += ["## 已检索到的题库依据", "", "\n\n---\n\n".join(queries), ""]
        for name, content in others:
            lines += [f"## 工具结果：{name}", "", content, ""]
    lines += [
        "## 中断现场",
        "",
        f"- loop 状态：{result.status}",
        f"- 已运行：{result.iterations} 轮",
        f"- 关键轨迹：{_format_tool_trace(result.trace, max_actions=6)}",
        "",
        "## 注意",
        "",
        "这不是完整诊断；未完成的步骤没有被补写，以上内容只来自已成功执行的工具结果。",
    ]
    return "\n".join(lines)


def _build_failed_report(reason: str, result: LoopResult | None = None) -> str:
    """失败说明同样显式标状态，避免被下游当成普通报告文本。"""
    lines = [
        "# 面试诊断失败",
        "",
        "> **状态：failed**",
        f"> **原因**：{reason}",
        "",
        "没有可用于降级报告的成功工具材料。",
    ]
    if result is not None:
        lines += [
            "",
            "## 中断现场",
            "",
            f"- loop 状态：{result.status}",
            f"- 已运行：{result.iterations} 轮",
            f"- 关键轨迹：{_format_tool_trace(result.trace, max_actions=6)}",
        ]
    lines += [
        "",
        "## 建议",
        "",
        "- 检查模型配置、额度或网络后重试",
        "- 如果反复失败，缩小面试稿并保留 session 现场排查",
    ]
    return "\n".join(lines)


def _format_tool_trace(trace: list[TurnTrace], *, max_actions: int = 12) -> str:
    """把结构化轨迹压成短错误信息；完整参数和结果仍留在会话消息里。"""
    actions = []
    for turn in trace:
        if not turn.tool_traces:
            actions.append(f"第{turn.iteration}轮(mode={turn.mode}, stop={turn.stop_reason})：无工具调用")
        for call in turn.tool_traces:
            args = " ".join(call.arguments.split())
            if len(args) > 120:
                args = args[:117] + "..."
            if call.outcome == "duplicate":
                detail = f"duplicate（同参数第{call.repeat_count}次，未执行）"
            elif call.outcome == "budget_exceeded":
                scope = "总预算" if call.budget_scope == "total" else "单项预算"
                detail = f"budget_exceeded（{scope}，未执行，{call.result_chars}字）"
            else:
                detail = f"{call.outcome}，{call.result_chars}字"
                if call.truncated:
                    detail += "，已截断"
                if call.result_preview:
                    detail += f"，预览：{call.result_preview}"
            actions.append(
                f"第{turn.iteration}轮(mode={turn.mode}, stop={turn.stop_reason}) "
                f"{call.name}({args}) -> {detail}"
            )
    if not actions:
        return "无运行轨迹"
    if len(actions) > max_actions:
        actions = ["..."] + actions[-max_actions:]
    return " -> ".join(actions)


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
