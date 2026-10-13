"""重试策略：可重试错误指数退避，不可重试错误直接抛（教程 03-query-engine）。

sleep 可注入：测试时传 lambda 秒数: None，不真等。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from offer_coach.engine.errors import QueryEngineError
from offer_coach.engine.models import ModelTurn


@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = 3  # 最多重试 3 次（即最多调用 4 次）
    base_delay: float = 1.0  # 首次等待秒数
    max_delay: float = 30.0  # 等待上限
    backoff: float = 2.0  # 退避倍数：1s → 2s → 4s


def with_retry(
    fn: Callable[[], ModelTurn],
    config: RetryConfig | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ModelTurn:
    """执行 fn，遇到可重试的 QueryEngineError 时按指数退避重试。"""
    config = config or RetryConfig()
    for attempt in range(config.max_retries + 1):
        try:
            return fn()
        except QueryEngineError as exc:
            if not exc.retryable or attempt == config.max_retries:
                raise
            # 服务器说等多久就等多久（retry_after），否则指数退避
            delay = (
                exc.retry_after
                if exc.retry_after is not None
                else min(config.base_delay * config.backoff**attempt, config.max_delay)
            )
            sleep(delay)
    raise AssertionError("不可达")  # pragma: no cover
