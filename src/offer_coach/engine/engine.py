"""QueryEngine：把 provider + 重试 + 成本账本组装成上层唯一入口（教程 03-query-engine）。

上层（未来的 agent loop）只调用 query()：预算检查 → 带重试调用 → 记账 → 返回。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from offer_coach.engine.cost import CostLedger
from offer_coach.engine.models import Message, ModelTurn
from offer_coach.engine.provider import Provider, ToolSchema
from offer_coach.engine.retry import RetryConfig, with_retry


@dataclass
class EngineConfig:
    provider: Provider
    model: str = "deepseek-chat"
    budget_usd: float = 1.0
    retry: RetryConfig = field(default_factory=RetryConfig)
    sleep: Callable[[float], None] = time.sleep  # 测试时注入 lambda: 不真等


class QueryEngine:
    """模型调用的总闸。所有 LLM 流量必经此层，天然统一记账、统一预算、统一重试。"""

    def __init__(self, config: EngineConfig) -> None:
        self._provider = config.provider
        self._retry = config.retry
        self._sleep = config.sleep
        self.ledger = CostLedger(budget_usd=config.budget_usd, model=config.model)

    def query(self, messages: list[Message], tools: list[ToolSchema] | None = None) -> ModelTurn:
        # 1. 预算检查必须在调用之前——超了就在开空调前跳闸
        self.ledger.check_budget()
        # 2. 带重试的调用（只重试"对方的问题"）
        turn = with_retry(
            lambda: self._provider.complete(messages, tools),
            config=self._retry,
            sleep=self._sleep,
        )
        # 3. 记账
        self.ledger.record(turn.usage)
        return turn

    def usage_summary(self) -> str:
        return self.ledger.summary()
