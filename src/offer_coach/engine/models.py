"""Query Engine 的数据模型。

跨模块数据一律用 Pydantic 模型（CLAUDE.md 开发约定），不用裸 dict。
"""

from __future__ import annotations

from pydantic import BaseModel


class ToolCall(BaseModel):
    """模型声明的一次工具调用。id 由模型生成，结果要用同一个 id 挂回（因果链）。"""

    id: str
    name: str
    arguments: str  # JSON 字符串，由调工具的一方解析


class Message(BaseModel):
    """一条对话消息。role 决定哪些字段有值：

    - system/user: content
    - assistant: content 和/或 tool_calls
    - tool: content + tool_call_id（挂回 assistant 的调用）
    """

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


class Usage(BaseModel):
    """一次模型调用的 token 消耗。"""

    input_tokens: int
    output_tokens: int


class ModelTurn(BaseModel):
    """模型这一轮的反应：要么直接回答，要么声明工具调用。"""

    message: Message
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens"
    usage: Usage
    request_id: str | None = None
