"""最小 agent loop：把 D2 学的循环第一次落到自己代码里（教程 04-tools-skills）。

一次循环 = 调模型 → 先记录 assistant 消息 → 有订单就执行工具、结果挂回历史 → 再调。
退出条件：模型不再下单（completed）/ 同一动作重复 3 次（stuck）/ 轮数耗尽（max_iterations）。
P0-2 增加工具声明预算：超预算后补工具回执，并给模型一轮无工具收尾机会。
P0-4 收尾轮放行零成本工具白名单：预算防的是烧钱工具，纯模板工具收走只会逼模型手写报告。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from offer_coach.context.manager import ContextManager
from offer_coach.engine.engine import QueryEngine
from offer_coach.engine.models import Message, ToolCall
from offer_coach.hooks.pipeline import HookPipeline
from offer_coach.tools.registry import ToolRegistry, execute_tool

LoopStatus = Literal["completed", "stuck", "max_iterations", "tool_budget_exceeded"]
ToolOutcome = Literal[
    "success", "empty", "error", "blocked", "duplicate", "budget_exceeded"
]
TurnMode = Literal["normal", "finalize"]
BudgetScope = Literal["total", "tool"]


class ToolBudget(BaseModel):
    """工具声明预算：按模型下单计数，不按工具成功次数计数。"""

    max_total_calls: int | None = None
    max_calls_by_tool: dict[str, int] = Field(default_factory=dict)


class ToolTrace(BaseModel):
    """一次工具声明的执行轨迹；完整结果仍在 messages，这里只留定位所需摘要。"""

    call_id: str
    name: str
    arguments: str
    repeat_count: int
    outcome: ToolOutcome
    result_chars: int = 0
    truncated: bool = False
    result_preview: str = ""
    budget_scope: BudgetScope | None = None


class TurnTrace(BaseModel):
    """一次模型回合及其工具轨迹；stop_reason 能区分终答、下单和输出截断。"""

    iteration: int
    stop_reason: str
    request_id: str | None = None
    mode: TurnMode = "normal"
    tool_traces: list[ToolTrace] = Field(default_factory=list)


@dataclass
class LoopResult:
    status: LoopStatus
    messages: list[Message]  # 完整历史（含工具往返），供上层/调试用
    final_text: str | None  # completed 时的最终回答
    iterations: int
    trace: list[TurnTrace]  # 结构化运行轨迹，供失败定位和回归测试用


def run_loop(
    engine: QueryEngine,
    registry: ToolRegistry,
    messages: list[Message],
    *,
    max_iterations: int = 10,
    max_repeats: int = 3,
    context: ContextManager | None = None,  # 可选：传了就每次调模型前裁剪历史（D7）
    hooks: HookPipeline | None = None,  # 可选：治理插件管线（D8 权限闸已改造为插件，D9）
    budget: ToolBudget | None = None,  # 可选：工具声明预算，耗尽后追加一轮收尾
    finalize_tools: tuple[str, ...] = (),  # P0-4：收尾轮仍可用的零成本工具白名单（由业务层点名）
) -> LoopResult:
    history = list(messages)
    fingerprints: Counter[tuple[str, str]] = Counter()  # 动作指纹 = 工具名+参数（不含 call_id）
    tool_declarations: Counter[str] = Counter()
    total_declarations = 0
    trace: list[TurnTrace] = []

    for iteration in range(1, max_iterations + 1):
        # 桌面管理：发给模型的历史先过裁剪；内部完整历史 history 不受影响
        outbound = context.fit(history) if context is not None else history
        turn = engine.query(outbound, tools=registry.schemas())
        assistant = turn.message
        turn_trace = TurnTrace(
            iteration=iteration,
            stop_reason=turn.stop_reason,
            request_id=turn.request_id,
        )
        trace.append(turn_trace)

        # 先记录后执行（D2 决策）：即使工具执行出岔子，历史里也有模型的原始订单
        history.append(assistant)

        if not assistant.tool_calls:
            return LoopResult("completed", history, assistant.content, iteration, trace)

        for call_index, call in enumerate(assistant.tool_calls):
            fp = (call.name, call.arguments)
            fingerprints[fp] += 1
            repeat_count = fingerprints[fp]
            if repeat_count >= max_repeats:
                # 防死循环哨兵：第三次声明没有执行，也必须留痕才知道为何止损
                turn_trace.tool_traces.append(ToolTrace(
                    call_id=call.id,
                    name=call.name,
                    arguments=call.arguments,
                    repeat_count=repeat_count,
                    outcome="duplicate",
                ))
                return LoopResult("stuck", history, None, iteration, trace)

            if budget is not None:
                budget_scope = _budget_scope(
                    budget,
                    tool_name=call.name,
                    next_total=total_declarations + 1,
                    next_tool_count=tool_declarations[call.name] + 1,
                )
                if budget_scope is not None:
                    # 超预算的当前订单及同一轮后续订单都补回执，保证订单/回执成对
                    _record_budget_exceeded_calls(
                        turn_trace,
                        history,
                        assistant.tool_calls[call_index:],
                        fingerprints,
                        budget_scope,
                        first_already_counted=True,
                    )
                    return _finalize_once(
                        engine,
                        registry,
                        history,
                        trace,
                        iteration + 1,
                        context,
                        fingerprints,
                        hooks,
                        finalize_tools,
                    )
                tool_declarations[call.name] += 1
                total_declarations += 1

            check_truncation = False
            if hooks is not None:
                # 插线板：执行前过 pre 插件（权限闸等），拦截原因喂回模型（失败当数据）
                allowed, block_message = hooks.run_pre(call.name, call.arguments)
                if not allowed:
                    result = block_message
                    outcome: ToolOutcome = "blocked"
                else:
                    result = execute_tool(registry, call)
                    outcome = _classify_tool_result(result)
                    # 执行后过 post 插件（结果压缩、审计等），结果可被改写
                    result = hooks.run_post(call.name, call.arguments, result)
                    check_truncation = True
            else:
                result = execute_tool(registry, call)
                outcome = _classify_tool_result(result)

            turn_trace.tool_traces.append(ToolTrace(
                call_id=call.id,
                name=call.name,
                arguments=call.arguments,
                repeat_count=repeat_count,
                outcome=outcome,
                result_chars=len(result),
                truncated=check_truncation and "已截断，原文" in result,
                result_preview=_result_preview(result),
            ))
            # tool_call_id 成对挂回（D2 决策）：模型靠订单号对账
            history.append(Message(role="tool", tool_call_id=call.id, content=result))

    return LoopResult("max_iterations", history, None, max_iterations, trace)


def _budget_scope(
    budget: ToolBudget,
    *,
    tool_name: str,
    next_total: int,
    next_tool_count: int,
) -> BudgetScope | None:
    """在声明入正式计数前预判：总预算优先，其次才是单项工具预算。"""
    if budget.max_total_calls is not None and next_total > budget.max_total_calls:
        return "total"
    tool_limit = budget.max_calls_by_tool.get(tool_name)
    if tool_limit is not None and next_tool_count > tool_limit:
        return "tool"
    return None


def _record_budget_exceeded_calls(
    turn_trace: TurnTrace,
    history: list[Message],
    calls: list[ToolCall],
    fingerprints: Counter[tuple[str, str]],
    scope: BudgetScope,
    *,
    first_already_counted: bool = False,
) -> None:
    """给未执行订单补回执；没有回执的历史不能让模型继续收尾。"""
    for index, call in enumerate(calls):
        fp = (call.name, call.arguments)
        if index > 0 or not first_already_counted:
            fingerprints[fp] += 1
        receipt = _budget_receipt(scope)
        turn_trace.tool_traces.append(ToolTrace(
            call_id=call.id,
            name=call.name,
            arguments=call.arguments,
            repeat_count=fingerprints[fp],
            outcome="budget_exceeded",
            result_chars=len(receipt),
            result_preview=_result_preview(receipt),
            budget_scope=scope,
        ))
        history.append(Message(role="tool", tool_call_id=call.id, content=receipt))


def _budget_receipt(scope: BudgetScope) -> str:
    if scope == "total":
        return "错误：总工具调用预算已耗尽，请基于已有信息直接收尾，不要再调用工具。"
    return "错误：单项工具调用预算已耗尽，请基于已有信息直接收尾，不要再调用工具。"


def _finalize_once(
    engine: QueryEngine,
    registry: ToolRegistry,
    history: list[Message],
    trace: list[TurnTrace],
    iteration: int,
    context: ContextManager | None,
    fingerprints: Counter[tuple[str, str]],
    hooks: HookPipeline | None,
    finalize_tools: tuple[str, ...],
) -> LoopResult:
    """预算耗尽后的收尾：菜单只剩白名单工具（业务层点名的零成本工具）。

    白名单订单正常执行（不计预算——预算防烧钱，它们免费），执行完递归进
    一轮真·无工具收尾（白名单置空）；白名单之外的订单照旧补回执止损。
    """
    menu = [s for s in registry.schemas() if s["name"] in finalize_tools]
    outbound = context.fit(history) if context is not None else history
    turn = engine.query(outbound, tools=menu)
    assistant = turn.message
    turn_trace = TurnTrace(
        iteration=iteration,
        stop_reason=turn.stop_reason,
        request_id=turn.request_id,
        mode="finalize",
    )
    trace.append(turn_trace)
    history.append(assistant)

    if not assistant.tool_calls:
        return LoopResult("completed", history, assistant.content, iteration, trace)

    whitelist_ids = {
        call.id for call in assistant.tool_calls
        if call.name in finalize_tools and registry.get(call.name) is not None
    }
    if not whitelist_ids:
        _record_budget_exceeded_calls(
            turn_trace,
            history,
            assistant.tool_calls,
            fingerprints,
            "total",
        )
        return LoopResult("tool_budget_exceeded", history, None, iteration, trace)

    for call in assistant.tool_calls:
        fp = (call.name, call.arguments)
        fingerprints[fp] += 1
        if call.id in whitelist_ids:
            result, outcome, truncated = _run_whitelisted_call(registry, hooks, call)
            turn_trace.tool_traces.append(ToolTrace(
                call_id=call.id,
                name=call.name,
                arguments=call.arguments,
                repeat_count=fingerprints[fp],
                outcome=outcome,
                result_chars=len(result),
                truncated=truncated,
                result_preview=_result_preview(result),
            ))
            history.append(Message(role="tool", tool_call_id=call.id, content=result))
        else:
            receipt = _budget_receipt("total")
            turn_trace.tool_traces.append(ToolTrace(
                call_id=call.id,
                name=call.name,
                arguments=call.arguments,
                repeat_count=fingerprints[fp],
                outcome="budget_exceeded",
                result_chars=len(receipt),
                result_preview=_result_preview(receipt),
                budget_scope="total",
            ))
            history.append(Message(role="tool", tool_call_id=call.id, content=receipt))
    # 白名单工具交付后，再补一轮真·无工具收尾让模型交终答
    return _finalize_once(
        engine, registry, history, trace, iteration + 1, context, fingerprints, hooks, ()
    )


def _run_whitelisted_call(
    registry: ToolRegistry,
    hooks: HookPipeline | None,
    call: ToolCall,
) -> tuple[str, ToolOutcome, bool]:
    """收尾轮的白名单执行：照样过插线板（权限闸不放假），只是不计预算。"""
    if hooks is None:
        result = execute_tool(registry, call)
        return result, _classify_tool_result(result), False
    allowed, block_message = hooks.run_pre(call.name, call.arguments)
    if not allowed:
        return block_message, "blocked", False
    result = execute_tool(registry, call)
    outcome = _classify_tool_result(result)
    result = hooks.run_post(call.name, call.arguments, result)
    return result, outcome, "已截断，原文" in result


def _classify_tool_result(result: str) -> ToolOutcome:
    """按 execute_tool 的文本合同归类结果，不在轨迹里复制完整内容。"""
    if not result.strip():
        return "empty"
    if result.startswith("错误："):
        return "error"
    return "success"


def _result_preview(result: str, *, max_chars: int = 120) -> str:
    """压成单行短预览；完整结果仍由 messages 保存，避免轨迹重复存储。"""
    preview = " ".join(result.split())
    if len(preview) > max_chars:
        return preview[:max_chars - 3] + "..."
    return preview
