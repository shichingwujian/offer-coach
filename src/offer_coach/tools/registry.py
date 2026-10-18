"""工具注册表 + 执行器（教程 04-tools-skills）。

核心真相：模型没有手，只会"下单"（tool_calls）。注册表是货架，
execute_tool 是跑腿的——按订单找函数、解析参数、执行、把结果包成文本。

铁律：execute_tool 永远不抛异常。任何失败都变成错误文本喂回模型，
让它自我纠错（D2 决策：失败当数据）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from offer_coach.engine.models import ToolCall
from offer_coach.engine.provider import ToolSchema


@dataclass
class ToolDef:
    """一个工具 = 给模型看的说明书 + Harness 真正执行的函数。"""

    name: str
    description: str  # 合同：模型只看这句话决定下不下单，措辞是工程问题
    parameters: dict  # JSON Schema：{"type": "object", "properties": {...}, "required": [...]}
    func: Callable[..., str]  # 入参必须与 parameters 里的字段同名


class ToolRegistry:
    """注册表：名字 → ToolDef 的字典。加工具 = register 一行，主循环零改动。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """摘掉一个工具（D14 消融对照组用：no-kb 配置没收检索工具）。"""
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def schemas(self) -> list[ToolSchema]:
        """导出给模型看的工具菜单（engine.query 的 tools 参数）。"""
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
        ]


def execute_tool(registry: ToolRegistry, call: ToolCall) -> str:
    """执行一张订单，返回结果文本。失败也返回错误文本——绝不抛异常。"""
    tool = registry.get(call.name)
    if tool is None:
        available = "、".join(sorted(registry._tools)) or "（空）"
        return f"错误：不存在名为 '{call.name}' 的工具。可用工具：{available}"

    # arguments 是字符串不是字典（模型输出的原始 JSON 文本），必须先解析
    try:
        args = json.loads(call.arguments or "{}")
    except json.JSONDecodeError as e:
        return f"错误：arguments 不是合法 JSON（{e}）。请检查后重新调用。"
    if not isinstance(args, dict):
        return "错误：arguments 必须是 JSON 对象，例如 {\"keyword\": \"Redis\"}。"

    missing = [k for k in tool.parameters.get("required", []) if k not in args]
    if missing:
        return f"错误：缺少必填参数 {missing}。参数表：{tool.parameters.get('properties', {})}"

    try:
        return str(tool.func(**args))
    except Exception as e:  #  noqa: BLE001 —— 故意兜底：失败当数据喂回模型，不是吞错
        return f"错误：工具 {call.name} 执行失败：{type(e).__name__}: {e}"
