"""Context 层：模型的桌面管理（教程 06-context-memory，v1 裁剪版，见 decisions.md D005）。

模型是金鱼：两次调用之间什么都不记得，"记忆"是我们每轮重发的 history。
历史是雪球，越滚越贵（input 按量计费且每轮重发）、越乱（注意力稀释）。
v1 策略：死保区（剧本+任务锚点）+ 滑窗区（从后往前装，预算满就扔老的）。

硬约束：tool 结果必须和它的 assistant 订单同进同出——孤儿订单会让 API 报错。
"""

from __future__ import annotations

from dataclasses import dataclass

from offer_coach.engine.models import Message

_MSG_OVERHEAD = 4  # 每条消息的固定开销（角色等元信息），粗算惯例


def estimate_tokens(text: str) -> int:
    """粗算 token 数：中文 1 字 ≈ 1 token，英文 4 字符 ≈ 1 token。

    滑窗只需要知道"大概多重"，误差 20% 不影响裁剪决策，所以不引入精确分词器。
    """
    cjk = sum(1 for ch in text if ord(ch) > 0x2E7F)
    other = len(text) - cjk
    return cjk + other // 4


@dataclass
class ContextConfig:
    max_tokens: int = 6000  # 桌面总预算（远小于 64K 窗口：省钱 + 防注意力稀释）
    keep_recent: int = 6  # 最近 N 条无论如何保住（保底上下文连贯）
    reserve_output: int = 1000  # 给模型回答预留的桌面空间


class ContextManager:
    """把历史裁剪到预算内。三条规则：死保、从后往前装、成对裁剪。"""

    def __init__(self, config: ContextConfig | None = None) -> None:
        self.config = config or ContextConfig()

    def fit(self, messages: list[Message]) -> list[Message]:
        budget = self.config.max_tokens - self.config.reserve_output
        if self._cost(messages) <= budget:
            return list(messages)  # 预算内：原样返回，一条不动

        # 死保区：开头所有 system + 第一条 user（任务锚点）
        pinned: list[Message] = []
        idx = 0
        while idx < len(messages) and messages[idx].role == "system":
            pinned.append(messages[idx])
            idx += 1
        if idx < len(messages) and messages[idx].role == "user":
            pinned.append(messages[idx])
            idx += 1

        # 滑窗区：从后往前按"轮块"装。assistant 订单 + 它的 tool 结果 = 一整块，同进同出
        kept: list[Message] = []
        cost = self._cost(pinned)
        for block in reversed(self._blocks(messages[idx:])):
            must = len(kept) < self.config.keep_recent  # 保底：最近 N 条不能扔
            if must or cost + self._cost(block) <= budget:
                kept = block + kept
                cost += self._cost(block)
            else:
                break
        return pinned + kept

    @staticmethod
    def _blocks(msgs: list[Message]) -> list[list[Message]]:
        """把消息切成块：带订单的 assistant 和它后面的 tool 结果绑成一整块。"""
        blocks: list[list[Message]] = []
        i = 0
        while i < len(msgs):
            m = msgs[i]
            if m.role == "assistant" and m.tool_calls:
                j = i + 1
                while j < len(msgs) and msgs[j].role == "tool":
                    j += 1
                blocks.append(msgs[i:j])
                i = j
            else:
                blocks.append([m])
                i += 1
        return blocks

    @staticmethod
    def _cost(msgs: list[Message]) -> int:
        total = 0
        for m in msgs:
            total += _MSG_OVERHEAD + estimate_tokens(m.content or "")
            for tc in m.tool_calls or []:
                total += estimate_tokens(tc.name) + estimate_tokens(tc.arguments)
        return total
