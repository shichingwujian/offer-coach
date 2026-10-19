"""Memory 层测试：档案柜增查改、写入插件的死规则、开局召回、diagnose 集成。

全程 FakeProvider + 临时库，离线、零成本、确定性（D003）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from offer_coach.cli import handle_command
from offer_coach.engine import EngineConfig, FakeProvider, QueryEngine, RetryConfig
from offer_coach.memory import MemoryStore, make_memory_hook, recall_block
from offer_coach.skills import diagnose, diagnose_run
from offer_coach.tools import default_registry


def no_sleep(_seconds: float) -> None:
    """测试用 sleep：不真等。"""


def make_engine(script: list[Any]) -> tuple[QueryEngine, FakeProvider]:
    provider = FakeProvider(script)
    engine = QueryEngine(
        EngineConfig(provider=provider, retry=RetryConfig(base_delay=0.01), sleep=no_sleep)
    )
    return engine, provider


# analyze 工具渲染后的固定格式（记忆插件靠这个格式解析分数）
WEAK_RENDERED = (
    "## 四维评分\n\n"
    "- 技术准确性：2/5 —— 把 RDB 说成 AOF\n"
    "- 结构化表达：4/5\n"
    "- 回答深度：1/5 —— 只背了名词\n"
    "- 沟通清晰度：4/5\n\n"
    "**总评**：基础薄弱"
)
# 模型按约定返回的原始 JSON（analyze 工具内部的模型输出）
WEAK_JSON = (
    '{"技术准确性": 2, "结构化表达": 4, "回答深度": 1, "沟通清晰度": 4,'
    ' "证据": {"技术准确性": "把 RDB 说成 AOF", "回答深度": "只背了名词"},'
    ' "总评": "基础薄弱"}'
)


class TestStore:
    """档案柜本体：增、查、改。"""

    def test_create_and_retrieve_by_type(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "m.db")
        store.create("weak_point", "技术准确性", {"score": 2})
        store.create("diagnosis_summary", "diag-1", {"date": "2026-10-14"})
        weaks = store.retrieve(type="weak_point")
        assert len(weaks) == 1
        assert weaks[0].key == "技术准确性"
        assert weaks[0].confidence == 0.5  # 新生记忆先观望
        assert weaks[0].value["score"] == 2

    def test_min_confidence_filter(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "m.db")
        low = store.create("weak_point", "回答深度", {"score": 1})
        store.create("weak_point", "沟通清晰度", {"score": 2})
        store.update(low, {"score": 1}, boost=True)  # 0.5 → 0.6
        seated = store.retrieve(type="weak_point", min_confidence=0.6)
        assert [e.key for e in seated] == ["回答深度"]

    def test_boost_caps_at_one(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "m.db")
        entry_id = store.create("weak_point", "技术准确性", {"score": 2})
        for _ in range(10):
            store.update(entry_id, {"score": 2}, boost=True)
        assert store.retrieve(type="weak_point", key="技术准确性")[0].confidence == 1.0

    def test_access_count_tracks_recall(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "m.db")
        store.create("weak_point", "回答深度", {"score": 1})
        store.retrieve(type="weak_point")
        entry = store.retrieve(type="weak_point")[0]
        assert entry.access_count == 2  # 被取过两次

    def test_profile_patch_merges(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "m.db")
        store.update_profile({"target_role": "后端开发"})
        store.update_profile({"total_diagnoses": 1})
        profile = store.get_profile()
        assert profile["target_role"] == "后端开发"  # 老字段没被覆盖
        assert profile["total_diagnoses"] == 1


class TestMemoryHook:
    """档案员插件：死规则——只看 analyze，只记低分，解析不到宁可不记。"""

    def test_ignores_other_tools(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "m.db")
        hook = make_memory_hook(store)
        assert hook("query_knowledge_base", "{}", WEAK_RENDERED) == WEAK_RENDERED
        assert store.stats()["total"] == 0

    def test_unparseable_result_writes_nothing(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "m.db")
        hook = make_memory_hook(store)
        result = hook("analyze_content", "{}", "随便一段没有分数的话")
        assert result == "随便一段没有分数的话"  # 旁观型插件永不改写结果
        assert store.stats()["total"] == 0

    def test_low_dims_written_high_dims_not(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "m.db")
        make_memory_hook(store)("analyze_content", "{}", WEAK_RENDERED)
        weaks = store.retrieve(type="weak_point")
        assert {w.key for w in weaks} == {"技术准确性", "回答深度"}  # 只有 <3 分的
        profile = store.get_profile()
        assert set(profile["weak_dimensions"]) == {"技术准确性", "回答深度"}
        assert profile["last_scores"]["技术准确性"] == 2

    def test_repeat_boosts_not_duplicates(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "m.db")
        hook = make_memory_hook(store)
        hook("analyze_content", "{}", WEAK_RENDERED)
        hook("analyze_content", "{}", WEAK_RENDERED)  # 同维度又考砸了
        weaks = store.retrieve(type="weak_point")
        assert len(weaks) == 2  # 不新增条目
        entry = store.retrieve(type="weak_point", key="技术准确性")[0]
        assert entry.confidence == 0.6  # 坐实度 +0.1
        assert entry.value["score"] == 2  # 内容更新为最近分数


class TestRecall:
    """开局召回：坐实度不够的不上桌面（一次考砸是意外）。"""

    def test_empty_store_returns_empty(self, tmp_path: Path) -> None:
        assert recall_block(MemoryStore(tmp_path / "m.db")) == ""

    def test_fresh_weak_not_recalled_until_seated(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "m.db")
        entry_id = store.create("weak_point", "回答深度", {"score": 1})
        assert "回答深度" not in recall_block(store)  # 0.5 坐实度不够
        store.update(entry_id, {"score": 1}, boost=True)  # → 0.6 坐实
        assert "回答深度" in recall_block(store)

    def test_profile_fields_rendered(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "m.db")
        store.update_profile({"target_role": "后端开发", "tech_stack": ["Python", "Go"]})
        block = recall_block(store)
        assert "目标岗位：后端开发" in block
        assert "Python、Go" in block


class TestDiagnoseWithMemory:
    """集成：连着诊断两次，第二次开局就该看到第一次留下的档案。"""

    def _script(self) -> list[Any]:
        return [
            FakeProvider.tool_turn("analyze_content", '{"transcript": "x"}', call_id="c1"),
            FakeProvider.text_turn(WEAK_JSON),  # analyze 内部查询消费这张
            FakeProvider.tool_turn("generate_report", '{"analysis": "a"}', call_id="c2"),
            FakeProvider.text_turn("报告全文"),
        ]

    def test_second_run_recalls_history(self, tmp_path: Path) -> None:
        transcript = tmp_path / "稿.txt"
        transcript.write_text("面试官：Redis 持久化？\n候选人：呃……", encoding="utf-8")
        store = MemoryStore(tmp_path / "m.db")

        engine1, _ = make_engine(self._script())
        diagnose(transcript, engine1, tmp_path / "q.db", memory=store)
        stats = store.stats()["by_type"]
        assert stats["weak_point"] == 2
        assert stats["diagnosis_summary"] == 1
        assert store.get_profile()["total_diagnoses"] == 1

        engine2, provider2 = make_engine(self._script())
        diagnose(transcript, engine2, tmp_path / "q.db", memory=store)
        # 第二次开局：system prompt 里带着第一次留下的档案
        system_prompt = provider2.calls[0][0].content or ""
        assert "历史档案" in system_prompt
        assert "技术准确性" in system_prompt
        # 同维度再考砸：坐实不新增
        assert store.stats()["by_type"]["weak_point"] == 2
        weak = store.retrieve(type="weak_point", key="技术准确性")[0]
        assert weak.confidence == 0.6
        assert store.get_profile()["total_diagnoses"] == 2

    def test_degraded_run_does_not_write_summary(self, tmp_path: Path) -> None:
        """降级报告不算完整诊断：低分弱点可留档，diagnosis_summary 不能记账。"""
        transcript = tmp_path / "稿.txt"
        transcript.write_text("面试官：Redis 持久化？\n候选人：呃……", encoding="utf-8")
        store = MemoryStore(tmp_path / "m.db")
        engine, _ = make_engine([
            FakeProvider.tool_turn("analyze_content", '{"transcript": "x"}', call_id="c1"),
            FakeProvider.text_turn(WEAK_JSON),  # analyze 内部查询消费这张
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c2"),
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c3"),
            FakeProvider.tool_turn("query_knowledge_base", '{"keyword": "Redis"}', call_id="c4"),
        ])

        result = diagnose_run(transcript, engine, tmp_path / "q.db", memory=store)

        assert result.status == "degraded"
        assert store.stats()["by_type"]["weak_point"] == 2
        assert "diagnosis_summary" not in store.stats()["by_type"]
        assert "total_diagnoses" not in store.get_profile()

    def test_no_memory_keeps_old_behavior(self, tmp_path: Path) -> None:
        """不传档案柜 = 老行为：剧本里没有历史档案段。"""
        transcript = tmp_path / "稿.txt"
        transcript.write_text("稿子", encoding="utf-8")
        engine, provider = make_engine([FakeProvider.text_turn("直接诊断")])
        diagnose(transcript, engine, tmp_path / "q.db")
        assert "历史档案" not in (provider.calls[0][0].content or "")


class TestMemoryCommands:
    """斜杠命令：/profile 写画像（直达电梯式死规则写入）、/memory 看柜子。"""

    def _rig(self, tmp_path: Path) -> tuple[QueryEngine, Any, MemoryStore]:
        engine, _ = make_engine([])
        registry = default_registry(engine, tmp_path / "q.db")
        store = MemoryStore(tmp_path / "m.db")
        return engine, registry, store

    def test_profile_set_and_show(self, tmp_path: Path) -> None:
        engine, registry, store = self._rig(tmp_path)
        assert "暂无画像" in handle_command("/profile", engine, registry, store)
        assert "已记住" in handle_command("/profile 岗位=后端开发", engine, registry, store)
        assert "后端开发" in handle_command("/profile", engine, registry, store)

    def test_profile_tech_stack_list(self, tmp_path: Path) -> None:
        engine, registry, store = self._rig(tmp_path)
        handle_command("/profile 技术栈=Python,Go", engine, registry, store)
        assert store.get_profile()["tech_stack"] == ["Python", "Go"]

    def test_profile_unknown_field_rejected(self, tmp_path: Path) -> None:
        engine, registry, store = self._rig(tmp_path)
        assert "不认识字段" in handle_command("/profile 身高=180", engine, registry, store)

    def test_memory_stats_command(self, tmp_path: Path) -> None:
        engine, registry, store = self._rig(tmp_path)
        store.create("weak_point", "回答深度", {"score": 1})
        output = handle_command("/memory", engine, registry, store)
        assert "记忆总数：1" in output and "回答深度" in output
