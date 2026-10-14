"""最小 agent loop：把 D2 学的循环第一次落到自己代码里（教程 04-tools-skills）。

一次循环 = 调模型 → 先记录 assistant 消息 → 有订单就执行工具、结果挂回历史 → 再调。
退出条件：模型不再下单（completed）/ 同一动作重复 3 次（stuck）/ 轮数耗尽（max_iterations）。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from offer_coach.context.manager import ContextManager
from offer_coach.engine.engine import QueryEngine
from offer_coach.engine.models import Message
from offer_coach.hooks.pipeline import HookPipeline
from offer_coach.tools.registry import ToolRegistry, execute_tool

LoopStatus = Literal["completed", "stuck", "max_iterations"]


@dataclass
class LoopResult:
    status: LoopStatus
    messages: list[Message]  # 完整历史（含工具往返），供上层/调试用
    final_text: str | None  # completed 时的最终回答
    iterations: int


def run_loop(
    engine: QueryEngine,
    registry: ToolRegistry,
    messages: list[Message],
    *,
    max_iterations: int = 10,
    max_repeats: int = 3,
    context: ContextManager | None = None,  # 可选：传了就每次调模型前裁剪历史（D7）
    hooks: HookPipeline | None = None,  # 可选：治理插件管线（D8 权限闸已改造为插件，D9）
) -> LoopResult:
    history = list(messages)
    fingerprints: Counter[tuple[str, str]] = Counter()  # 动作指纹 = 工具名+参数（不含 call_id）

    for iteration in range(1, max_iterations + 1):
        # 桌面管理：发给模型的历史先过裁剪；内部完整历史 history 不受影响
        outbound = context.fit(history) if context is not None else history
        turn = engine.query(outbound, tools=registry.schemas())
        assistant = turn.message

        # 先记录后执行（D2 决策）：即使工具执行出岔子，历史里也有模型的原始订单
        history.append(assistant)

        if not assistant.tool_calls:
            return LoopResult("completed", history, assistant.content, iteration)

        for call in assistant.tool_calls:
            fp = (call.name, call.arguments)
            fingerprints[fp] += 1
            if fingerprints[fp] >= max_repeats:
                # 防死循环哨兵：模型在同一动作上打转了，止损退出
                return LoopResult("stuck", history, None, iteration)
            if hooks is not None:
                # 插线板：执行前过 pre 插件（权限闸等），拦截原因喂回模型（失败当数据）
                allowed, block_message = hooks.run_pre(call.name, call.arguments)
                if not allowed:
                    result = block_message
                else:
                    result = execute_tool(registry, call)
                    # 执行后过 post 插件（结果压缩、审计等），结果可被改写
                    result = hooks.run_post(call.name, call.arguments, result)
            else:
                result = execute_tool(registry, call)
            # tool_call_id 成对挂回（D2 决策）：模型靠订单号对账
            history.append(Message(role="tool", tool_call_id=call.id, content=result))

    return LoopResult("max_iterations", history, None, max_iterations)
