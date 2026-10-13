"""成本账本：所有 LLM 调用的 token 和成本统一记在这里（教程 03-query-engine 的 Token Counter）。

为什么是"总闸记账"而不是各工具各记各的：预算检查必须发生在调用之前，
只有所有调用必经的这一层能做这件事。
"""

from __future__ import annotations

from offer_coach.engine.errors import QueryEngineError
from offer_coach.engine.models import Usage

# 每 token 价格（美元）：(输入价, 输出价)。DeepSeek 官方价约为 GPT 的零头。
DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.27 / 1_000_000, 1.10 / 1_000_000),
    "default": (0.27 / 1_000_000, 1.10 / 1_000_000),
}


class CostLedger:
    """预算与记账。超预算时 check_budget 在调用前拉闸。"""

    def __init__(
        self,
        budget_usd: float = 1.0,
        pricing: dict[str, tuple[float, float]] | None = None,
        model: str = "deepseek-chat",
    ) -> None:
        self.budget_usd = budget_usd
        self._pricing = pricing or DEFAULT_PRICING
        self._model = model
        self.spent_usd = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.requests = 0

    def check_budget(self) -> None:
        if self.spent_usd >= self.budget_usd:
            raise QueryEngineError.budget_exceeded(self.spent_usd, self.budget_usd)

    def record(self, usage: Usage) -> float:
        """记一次调用的账，返回本次成本（美元）。"""
        in_price, out_price = self._pricing.get(self._model, self._pricing["default"])
        cost = usage.input_tokens * in_price + usage.output_tokens * out_price
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.spent_usd += cost
        self.requests += 1
        return cost

    def summary(self) -> str:
        return (
            f"请求 {self.requests} 次 | "
            f"token {self.input_tokens}入 + {self.output_tokens}出 | "
            f"成本 ${self.spent_usd:.6f} / 预算 ${self.budget_usd:.2f}"
        )
