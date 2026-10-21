"""充值冒烟：用一次最便宜的调用确认 API 额度到账，再跑长稿验收。

用法：.venv/Scripts/python.exe scripts/ping_api.py
成功打印余额信号（一次正常返回 + 本次成本），失败打印错误类型。
"""

from offer_coach.engine import EngineConfig, Message, OpenAIProvider, QueryEngine
from offer_coach.engine.errors import QueryEngineError


def main() -> None:
    try:
        provider = OpenAIProvider.from_env()
    except QueryEngineError as e:
        print(f"环境未配置：{e}")
        raise SystemExit(1)
    engine = QueryEngine(EngineConfig(provider=provider))
    try:
        turn = engine.query([Message(role="user", content="用五个字回答：1+1等于几")])
    except QueryEngineError as e:
        print(f"调用失败：{type(e).__name__}: {e}")
        raise SystemExit(1)
    print(f"模型回了：{turn.message.content!r}")
    print(f"本次账单：{engine.usage_summary()}")


if __name__ == "__main__":
    main()
