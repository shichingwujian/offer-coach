"""Hook 层：执行链的插线板（教程 08-hook-command）。

没有插座时，每加一种治理（权限/审计/压缩/记忆）都要打开 loop 的身体塞代码。
有了插座：治理逻辑做成插件，pre_tool（执行前）和 post_tool（执行后）两排插孔，
loop 从此对修改关闭、对扩展开放（注册表原则的第三次兑现）。

- PreToolHook(工具名, 参数) -> (放行?, 拦截原因)：任一插件拦截即短路，后面的不再执行
- PostToolHook(工具名, 参数, 结果) -> 新结果：插件可改写结果（如剪短长输出）
"""

from __future__ import annotations

from collections.abc import Callable

PreToolHook = Callable[[str, str], tuple[bool, str]]
PostToolHook = Callable[[str, str, str], str]


class HookPipeline:
    """两排插孔 + 按序执行。插件注册顺序 = 执行顺序。"""

    def __init__(self) -> None:
        self._pre: list[PreToolHook] = []
        self._post: list[PostToolHook] = []

    def add_pre(self, hook: PreToolHook) -> None:
        self._pre.append(hook)

    def add_post(self, hook: PostToolHook) -> None:
        self._post.append(hook)

    def run_pre(self, tool_name: str, arguments: str) -> tuple[bool, str]:
        """执行前过一遍 pre 插件。任一拦截 → 短路返回（后面的插件不再执行）。"""
        for hook in self._pre:
            allowed, message = hook(tool_name, arguments)
            if not allowed:
                return False, message
        return True, ""

    def run_post(self, tool_name: str, arguments: str, result: str) -> str:
        """执行后过一遍 post 插件，结果可被逐级改写。"""
        for hook in self._post:
            result = hook(tool_name, arguments, result)
        return result


def truncate_hook(max_chars: int = 2000) -> PostToolHook:
    """结果压缩插件（实战版）：工具输出太长就剪短再喂模型，防上下文膨胀。

    题库一道题的"高手答"可能几千字，全塞进历史桌面一下就满了。
    """

    def hook(_tool_name: str, _arguments: str, result: str) -> str:
        if len(result) <= max_chars:
            return result
        return result[:max_chars] + f"\n……（输出过长，已截断，原文 {len(result)} 字）"

    return hook
