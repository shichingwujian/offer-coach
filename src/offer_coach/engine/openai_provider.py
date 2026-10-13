"""OpenAI 兼容 Provider：DeepSeek / GPT-4o / Qwen 等共用（教程 03-query-engine）。

职责只有两个：
1. 把我们的协议中立 Message 翻译成 OpenAI 格式，把响应翻译回 ModelTurn
2. 把 SDK 异常翻译成我们的 QueryEngineError 分类
"""

from __future__ import annotations

import os
from typing import Any

import openai

from offer_coach.engine.errors import QueryEngineError
from offer_coach.engine.models import Message, ModelTurn, ToolCall, Usage
from offer_coach.engine.provider import ToolSchema

_STOP_REASON_MAP = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
}


def _to_openai_message(m: Message) -> dict[str, Any]:
    if m.role == "tool":
        # 工具结果：用 tool_call_id 挂回模型的调用（因果链）
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content or ""}
    d: dict[str, Any] = {"role": m.role, "content": m.content or ""}
    if m.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in m.tool_calls
        ]
    return d


class OpenAIProvider:
    """OpenAI 兼容接口的 Provider。client 可注入，测试时用桩对象，不联网。"""

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_env(cls) -> OpenAIProvider:
        """从环境变量构造。key 未配置时明确报错（环境契约），禁止机械兜底。"""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise QueryEngineError.auth(
                "缺少 OPENAI_API_KEY：请复制 .env.example 为 .env 并填入你的 key"
            )
        base_url = os.environ.get("OPENAI_BASE_URL") or None
        model = os.environ.get("OPENAI_MODEL", "deepseek-chat")
        return cls(openai.OpenAI(api_key=api_key, base_url=base_url), model)

    def complete(
        self, messages: list[Message], tools: list[ToolSchema] | None = None
    ) -> ModelTurn:
        openai_tools = (
            [{"type": "function", "function": t} for t in tools] if tools else None
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[_to_openai_message(m) for m in messages],
                tools=openai_tools,
            )
        except openai.RateLimitError as e:
            raise QueryEngineError.rate_limit() from e
        except openai.APITimeoutError as e:
            raise QueryEngineError.timeout() from e
        except openai.APIConnectionError as e:
            raise QueryEngineError.timeout() from e
        except openai.AuthenticationError as e:
            raise QueryEngineError.auth(str(e)) from e
        except openai.BadRequestError as e:
            raise QueryEngineError.invalid_request(str(e)) from e
        except openai.APIStatusError as e:
            if e.status_code >= 500:
                raise QueryEngineError.server(str(e)) from e
            raise QueryEngineError.invalid_request(str(e)) from e

        choice = resp.choices[0]
        msg = choice.message
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments or "")
            for tc in (msg.tool_calls or [])
        ]
        usage = Usage(
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
        )
        return ModelTurn(
            message=Message(
                role="assistant",
                content=msg.content,
                tool_calls=tool_calls or None,
            ),
            stop_reason=_STOP_REASON_MAP.get(choice.finish_reason or "", "end_turn"),
            usage=usage,
            request_id=getattr(resp, "id", None),
        )
