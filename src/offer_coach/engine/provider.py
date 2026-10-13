"""Provider 接口 + FakeProvider。

Provider 是"插座"（decisions.md D003）：QueryEngine 只认 complete() 这一个方法，
测试时插 FakeProvider（离线、零成本、确定性），生产时插 OpenAIProvider（真模型）。
"""

from __future__ import annotations

from collections import deque
from typing import Protocol

from offer_coach.engine.errors import QueryEngineError
from offer_coach.engine.models import Message, ModelTurn, ToolCall, Usage

ToolSchema = dict  # {"name": ..., "description": ..., "parameters": {...}}


class Provider(Protocol):
    """模型提供方接口：收消息历史和工具清单，返回模型这一轮的反应。"""

    def complete(
        self, messages: list[Message], tools: list[ToolSchema] | None = None
    ) -> ModelTurn: ...


class FakeProvider:
    """脚本化假模型：按脚本顺序依次"返回 ModelTurn"或"抛出错误"。

    用法：
        provider = FakeProvider([FakeProvider.text_turn("你好")])
        turn = provider.complete([Message(role="user", content="hi")])
    """

    def __init__(self, script: list[ModelTurn | QueryEngineError]) -> None:
        self._script = deque(script)
        self.calls: list[list[Message]] = []  # 记录每次收到的历史，供测试断言

    def complete(
        self, messages: list[Message], tools: list[ToolSchema] | None = None
    ) -> ModelTurn:
        self.calls.append(list(messages))
        if not self._script:
            raise QueryEngineError.server("（FakeProvider 脚本耗尽）")
        item = self._script.popleft()
        if isinstance(item, Exception):
            raise item
        return item

    @staticmethod
    def text_turn(content: str, input_tokens: int = 10, output_tokens: int = 5) -> ModelTurn:
        """构造一个"直接回答"的回合。"""
        return ModelTurn(
            message=Message(role="assistant", content=content),
            stop_reason="end_turn",
            usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
        )

    @staticmethod
    def tool_turn(
        name: str, arguments: str, call_id: str = "call_1", input_tokens: int = 10
    ) -> ModelTurn:
        """构造一个"我要调工具"的回合。"""
        return ModelTurn(
            message=Message(
                role="assistant",
                content=None,
                tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
            ),
            stop_reason="tool_use",
            usage=Usage(input_tokens=input_tokens, output_tokens=0),
        )
