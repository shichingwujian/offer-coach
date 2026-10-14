"""Hook + Command 测试：插线板执行顺序、短路、结果改写、斜杠命令。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from offer_coach.cli import handle_command
from offer_coach.engine import (
    EngineConfig,
    FakeProvider,
    Message,
    QueryEngine,
    RetryConfig,
)
from offer_coach.hooks import HookPipeline, truncate_hook
from offer_coach.knowledge import build_db
from offer_coach.permission import PermissionGate
from offer_coach.tools import default_registry, run_loop


def no_sleep(_seconds: float) -> None:
    """测试用 sleep：不真等。"""


def make_engine(script: list[Any]) -> tuple[QueryEngine, FakeProvider]:
    provider = FakeProvider(script)
    engine = QueryEngine(
        EngineConfig(provider=provider, retry=RetryConfig(base_delay=0.01), sleep=no_sleep)
    )
    return engine, provider


class TestPipeline:
    def test_pre_hooks_run_in_order(self) -> None:
        order: list[str] = []
        pipeline = HookPipeline()
        pipeline.add_pre(lambda n, a: order.append("first") or (True, ""))
        pipeline.add_pre(lambda n, a: order.append("second") or (True, ""))
        pipeline.run_pre("tool", "{}")
        assert order == ["first", "second"]  # 注册顺序 = 执行顺序

    def test_pre_block_short_circuits(self) -> None:
        order: list[str] = []
        pipeline = HookPipeline()
        pipeline.add_pre(lambda n, a: order.append("blocker") or (False, "不行"))
        pipeline.add_pre(lambda n, a: order.append("never") or (True, ""))
        allowed, msg = pipeline.run_pre("tool", "{}")
        assert not allowed and msg == "不行"
        assert order == ["blocker"]  # 短路：后面的插件不再执行

    def test_post_hooks_rewrite_result_stepwise(self) -> None:
        pipeline = HookPipeline()
        pipeline.add_post(lambda n, a, r: r + "→A")
        pipeline.add_post(lambda n, a, r: r + "→B")
        assert pipeline.run_post("t", "{}", "结果") == "结果→A→B"  # 逐级改写

    def test_truncate_hook_shortens_long_output(self) -> None:
        hook = truncate_hook(max_chars=10)
        assert "已截断" in hook("t", "{}", "长" * 100)
        assert hook("t", "{}", "短") == "短"  # 短的不动


class TestPermissionAsPlugin:
    """权限闸改造为插件后，D8 的行为一个不能少。"""

    def test_gate_as_hook_blocks_and_feeds_back(self, tmp_path: Path) -> None:
        src = tmp_path / "bank"
        cat = src / "01-t"
        cat.mkdir(parents=True)
        (cat / "index.md").write_text("### Q：测试题？\n\n内容。", encoding="utf-8")
        db = tmp_path / "q.db"
        build_db(src, db)

        engine, _ = make_engine([
            FakeProvider.tool_turn("hack_tool", "{}", call_id="c1"),
            FakeProvider.text_turn("明白，我换用合法工具。"),
        ])
        gate = PermissionGate(ask=lambda q: True)
        pipeline = HookPipeline()
        pipeline.add_pre(gate.as_hook())

        result = run_loop(engine, default_registry(engine, db),
                          [Message(role="user", content="hi")], hooks=pipeline)

        assert result.status == "completed"
        assert "默认拒绝" in (result.messages[2].content or "")  # 拦截原因喂回了模型
        assert gate.audit[0]["action"] == "deny"  # 审计照常留痕


class TestCommands:
    """斜杠命令：绕过模型，确定性直达，零 token。"""

    def test_cost_command(self, tmp_path: Path) -> None:
        engine, _ = make_engine([])
        registry = default_registry(engine, tmp_path / "q.db")
        assert "账单" in handle_command("/cost", engine, registry)

    def test_tools_command(self, tmp_path: Path) -> None:
        engine, _ = make_engine([])
        registry = default_registry(engine, tmp_path / "q.db")
        output = handle_command("/tools", engine, registry)
        assert "query_knowledge_base" in output

    def test_exit_returns_none(self, tmp_path: Path) -> None:
        engine, _ = make_engine([])
        registry = default_registry(engine, tmp_path / "q.db")
        assert handle_command("/exit", engine, registry) is None

    def test_unknown_command_help(self, tmp_path: Path) -> None:
        engine, _ = make_engine([])
        registry = default_registry(engine, tmp_path / "q.db")
        assert "未知命令" in handle_command("/巴拉巴拉", engine, registry)
