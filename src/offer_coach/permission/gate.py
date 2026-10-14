"""Permission 层：权限闸门（教程 07-permission-session，v1 简化版）。

模型下的每张订单，执行前先过闸。防线设在 Harness 而不是模型身上——
提示词注入能骗过模型，但骗不过代码（闸门是死的）。

原则：默认拒绝，显式允许（白名单）。漏写一个工具 = 误拦（小不便），
而不是漏放一个危险操作（安全事故）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

Action = Literal["allow", "confirm", "deny"]


@dataclass
class PermissionRule:
    tool: str  # 工具名，"*" 表示兜底规则
    action: Action
    reason: str  # 给用户看的解释


# 默认规则表：三个内置工具的定级。没配规则的工具 = 默认拒绝
DEFAULT_RULES: list[PermissionRule] = [
    PermissionRule("query_knowledge_base", "allow", "只读检索，无副作用"),
    PermissionRule("generate_report", "allow", "纯模板渲染，无副作用"),
    PermissionRule("analyze_content", "confirm", "调用 LLM 会消耗 token"),
]


class PermissionGate:
    """权限闸门。ask 是注入的"问人类"函数：CLI 递真询问，测试递自动回答（依赖注入第 4 次）。"""

    def __init__(
        self,
        ask: Callable[[str], bool],
        rules: list[PermissionRule] | None = None,
    ) -> None:
        self._ask = ask
        self._rules = rules or DEFAULT_RULES
        self._remembered: set[str] = set()  # 本次会话已批准过的工具（首次问，后续记住）
        self.audit: list[dict] = []  # 审计日志：每次决策都留痕

    def check(self, tool_name: str) -> tuple[bool, str]:
        """审查一张订单。返回 (是否放行, 原因/结果说明)。"""
        rule = self._match(tool_name)
        if rule is None:
            return self._record(tool_name, "deny", "rule", False,
                                f"没有为 '{tool_name}' 配置权限规则（默认拒绝）")

        if rule.action == "allow":
            return self._record(tool_name, "allow", "rule", True, rule.reason)

        if rule.action == "deny":
            return self._record(tool_name, "deny", "rule", False, rule.reason)

        # confirm：人在环中
        if tool_name in self._remembered:
            return self._record(tool_name, "allow", "remembered", True, "本次会话已批准过")
        approved = self._ask(f"工具 {tool_name}：{rule.reason}。允许执行吗？[y/N] ")
        if approved:
            self._remembered.add(tool_name)
            return self._record(tool_name, "allow", "user", True, "用户批准")
        return self._record(tool_name, "deny", "user", False, "用户拒绝了此操作")

    def as_hook(self) -> Callable[[str, str], tuple[bool, str]]:
        """把闸门包装成 pre_tool 插件（D9：从 loop 内联代码改造为可插拔插件）。"""

        def hook(tool_name: str, _arguments: str) -> tuple[bool, str]:
            allowed, reason = self.check(tool_name)
            if allowed:
                return True, ""
            return False, f"权限闸门拒绝执行 {tool_name}：{reason}"

        return hook

    def _match(self, tool_name: str) -> PermissionRule | None:
        for rule in self._rules:
            if rule.tool == tool_name:
                return rule
        for rule in self._rules:
            if rule.tool == "*":
                return rule
        return None

    def _record(
        self, tool: str, action: Action, by: str, allowed: bool, reason: str
    ) -> tuple[bool, str]:
        self.audit.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "tool": tool, "action": action, "by": by,
            "allowed": allowed, "reason": reason,
        })
        return allowed, reason
