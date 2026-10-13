"""Query Engine 的错误分类。

设计原则（来自教程 03-query-engine）：不是所有错误都该重试。
先分类，再决定策略——可重试的（对方的问题）指数退避，不可重试的（你的问题）直接抛。
"""

from __future__ import annotations

# 错误类别
RATE_LIMIT = "rate_limit"  # 429，限流，等一等可重试
TIMEOUT = "timeout"  # 请求超时，可重试
SERVER = "server"  # 5xx，服务器故障，可重试
INVALID_REQUEST = "invalid_request"  # 400，请求本身有问题，重试无意义
AUTH = "auth"  # 401/403，凭证错误，重试无意义
BUDGET = "budget"  # 预算耗尽，拒绝调用


class QueryEngineError(Exception):
    """Query Engine 统一错误。category 决定 handling，retryable 决定是否重试。"""

    def __init__(
        self,
        message: str,
        category: str,
        retryable: bool,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.retry_after = retry_after  # 服务器建议的等待秒数（429 响应可能携带）

    @classmethod
    def rate_limit(cls, retry_after: float | None = None) -> QueryEngineError:
        return cls("模型 API 限流（429）", RATE_LIMIT, retryable=True, retry_after=retry_after)

    @classmethod
    def timeout(cls) -> QueryEngineError:
        return cls("模型 API 请求超时", TIMEOUT, retryable=True)

    @classmethod
    def server(cls, detail: str = "") -> QueryEngineError:
        return cls(f"模型 API 服务器故障（5xx）{detail}", SERVER, retryable=True)

    @classmethod
    def invalid_request(cls, detail: str) -> QueryEngineError:
        return cls(f"请求参数错误（400）：{detail}", INVALID_REQUEST, retryable=False)

    @classmethod
    def auth(cls, detail: str) -> QueryEngineError:
        return cls(f"鉴权失败（401/403）：{detail}", AUTH, retryable=False)

    @classmethod
    def budget_exceeded(cls, spent: float, budget: float) -> QueryEngineError:
        return cls(
            f"预算耗尽：已花 ${spent:.4f} / 预算 ${budget:.4f}，拒绝继续调用",
            BUDGET,
            retryable=False,
        )
