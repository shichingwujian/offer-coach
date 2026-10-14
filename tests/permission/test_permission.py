"""Permission + Session 测试：闸门决策、审计、存档读档、loop 集成。

ask 全部注入假回调（自动批准/拒绝），不卡键盘——依赖注入第 4 次实战。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from offer_coach.engine import EngineConfig, FakeProvider, Message, QueryEngine, RetryConfig
from offer_coach.knowledge import build_db
from offer_coach.permission import PermissionGate
from offer_coach.session import load_session, save_session
from offer_coach.skills import diagnose


def no_sleep(_seconds: float) -> None:
    """测试用 sleep：不真等。"""


def make_engine(script: list[Any]) -> tuple[QueryEngine, FakeProvider]:
    provider = FakeProvider(script)
    engine = QueryEngine(
        EngineConfig(provider=provider, retry=RetryConfig(base_delay=0.01), sleep=no_sleep)
    )
    return engine, provider


class TestGate:
    def test_allow_rule_passes(self) -> None:
        gate = PermissionGate(ask=lambda q: True)
        allowed, _ = gate.check("query_knowledge_base")
        assert allowed
        assert gate.audit[-1]["action"] == "allow"  # 审计留痕

    def test_unknown_tool_denied_by_default(self) -> None:
        gate = PermissionGate(ask=lambda q: True)
        allowed, reason = gate.check("hack_the_planet")
        assert not allowed
        assert "默认拒绝" in reason  # 白名单：没配规则一律拦

    def test_confirm_approved_then_remembered(self) -> None:
        asked: list[str] = []
        gate = PermissionGate(ask=lambda q: asked.append(q) or True)  # 自动批准并记次数
        gate.check("analyze_content")
        gate.check("analyze_content")  # 第二次
        assert len(asked) == 1  # 首次问，之后记住
        assert gate.audit[-1]["by"] == "remembered"

    def test_confirm_denied(self) -> None:
        gate = PermissionGate(ask=lambda q: False)  # 自动拒绝
        allowed, reason = gate.check("analyze_content")
        assert not allowed and "用户拒绝" in reason


class TestGateInLoop:
    """闸门拒绝也走"失败当数据"：原因喂回模型，loop 不崩。"""

    def test_denied_tool_result_fed_back(self, tmp_path: Path) -> None:
        src = tmp_path / "bank"
        cat = src / "01-t"
        cat.mkdir(parents=True)
        (cat / "index.md").write_text("### Q：测试题？\n\n内容。", encoding="utf-8")
        db = tmp_path / "q.db"
        build_db(src, db)
        transcript = tmp_path / "稿.txt"
        transcript.write_text("一段面试回答", encoding="utf-8")

        engine, _ = make_engine([
            FakeProvider.tool_turn("analyze_content", '{"transcript": "x"}', call_id="c1"),
            FakeProvider.text_turn("明白，那我不用分析了，直接给结论。"),
        ])
        gate = PermissionGate(ask=lambda q: False)  # 用户拒绝花钱
        report = diagnose(transcript, engine, db, gate=gate)

        assert "直接给结论" in report  # 模型收到拒绝原因，换路走完了
        assert gate.audit[0]["allowed"] is False


class TestSession:
    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        msgs = [
            Message(role="system", content="剧本"),
            Message(role="user", content="稿子"),
            Message(role="assistant", content="回答"),
        ]
        path = tmp_path / "sessions" / "s1.json"
        save_session(path, msgs)
        loaded = load_session(path)
        assert [m.role for m in loaded] == ["system", "user", "assistant"]
        assert loaded[1].content == "稿子"

    def test_load_missing_raises(self, tmp_path: Path) -> None:
        import pytest
        with pytest.raises(FileNotFoundError):
            load_session(tmp_path / "不存在.json")

    def test_diagnose_saves_session(self, tmp_path: Path) -> None:
        src = tmp_path / "bank"
        cat = src / "01-t"
        cat.mkdir(parents=True)
        (cat / "index.md").write_text("### Q：测试题？\n\n内容。", encoding="utf-8")
        db = tmp_path / "q.db"
        build_db(src, db)
        transcript = tmp_path / "稿.txt"
        transcript.write_text("一段面试回答", encoding="utf-8")
        session = tmp_path / "sessions" / "s.json"

        engine, _ = make_engine([FakeProvider.text_turn("报告")])
        diagnose(transcript, engine, db, session_path=session)

        assert session.exists()  # 存档落盘
        assert load_session(session)[-1].content == "报告"  # 最后一条是最终回答
