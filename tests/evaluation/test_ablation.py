"""D14 消融测试：LLM 裁判、跑器矩阵、汇总表 + diagnose 的消融开关。

跑诊断和判卷的函数都是注入的（DI 第 8、9 次）：测试喂罐头，零真模型调用。
真裁判 make_judge 用 FakeProvider 脚本验证提示词和 fail-closed 解析。
diagnose 开关用 FakeProvider 验证剧本替换和工具摘除。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from offer_coach.engine import EngineConfig, FakeProvider, QueryEngine, RetryConfig
from offer_coach.evaluation import (
    AblationCase,
    Mine,
    format_ablation,
    load_mines,
    make_judge,
    run_ablation,
    write_run_log,
)
from offer_coach.evaluation.ablation import _parse_judgments
from offer_coach.skills import diagnose
from offer_coach.tools import default_registry

TWO_MINES = [
    Mine(name="雷A", wrong="候选人说地球是平的", correct="地球是近似球体"),
    Mine(name="雷B", wrong="候选人说水往高处流", correct="水往低处流"),
]
CASE = AblationCase(transcript="t01.md", mines=TWO_MINES)


def _verdict_json(*verdicts: tuple[str, bool, str]) -> str:
    """拼一份裁判输出：[(雷名, 中不中, 证据), ...] → JSON 数组文本。"""
    return json.dumps(
        [{"name": n, "hit": h, "evidence": e} for n, h, e in verdicts], ensure_ascii=False
    )


class TestParseJudgments:
    """fail-closed 是尺子的命：任何一步对不上，该雷不中。"""

    def test_normal_parse(self) -> None:
        text = _verdict_json(("雷A", True, "报告指出地球是平的这个说法错误"), ("雷B", False, ""))
        assert _parse_judgments(text, TWO_MINES) == {"雷A": True, "雷B": False}

    def test_hit_without_evidence_is_miss(self) -> None:
        """空口说"挖到了"不算：命中必须带报告原话。"""
        text = _verdict_json(("雷A", True, ""))
        assert _parse_judgments(text, TWO_MINES) == {"雷A": False}

    def test_garbage_output_all_miss(self) -> None:
        assert _parse_judgments("裁判说了一堆废话没给 JSON", TWO_MINES) == {}

    def test_broken_json_all_miss(self) -> None:
        assert _parse_judgments('[{"name": "雷A", "hit": tru', TWO_MINES) == {}

    def test_unknown_mine_name_dropped(self) -> None:
        """裁判编了清单外的雷名：不认识的直接扔，已知雷不受影响。"""
        text = _verdict_json(("雷C（不存在的雷）", True, "证据"), ("雷B", True, "报告指出水往高处流是错的"))
        assert _parse_judgments(text, TWO_MINES) == {"雷B": True}

    def test_json_embedded_in_prose(self) -> None:
        """裁判前后裹了废话也能挖出 JSON 数组。"""
        text = "好的，判卷结果如下：\n" + _verdict_json(("雷A", True, "原话证据")) + "\n以上。"
        assert _parse_judgments(text, TWO_MINES) == {"雷A": True}


class TestMakeJudge:
    """真裁判：提示词里必须带标准答案，判卷结果按 fail-closed 聚合。"""

    def _engine(self, reply: str) -> QueryEngine:
        return QueryEngine(
            EngineConfig(
                provider=FakeProvider([FakeProvider.text_turn(reply)]),
                retry=RetryConfig(base_delay=0.01),
                sleep=lambda s: None,
            )
        )

    def test_prompt_carries_rubric(self) -> None:
        """裁判的卷子上必须印着每颗雷的 wrong/correct——否则它只能靠猜。"""
        engine = self._engine(_verdict_json(("雷A", True, "证据"), ("雷B", False, "")))
        make_judge(engine)("一份报告", TWO_MINES)
        prompt = engine._provider.calls[0][0].content  # type: ignore[attr-defined]
        assert "地球是平的" in prompt and "地球是近似球体" in prompt
        assert "水往高处流" in prompt

    def test_hits_aggregated(self) -> None:
        engine = self._engine(_verdict_json(("雷A", True, "原话"), ("雷B", False, "")))
        hits, missed = make_judge(engine)("报告", TWO_MINES)
        assert hits == 1 and missed == ["雷B"]

    def test_unparseable_reply_all_miss(self) -> None:
        """裁判翻车 = 全不中（宁可漏记，不可多记）。"""
        engine = self._engine("我觉得都挺好")
        hits, missed = make_judge(engine)("报告", TWO_MINES)
        assert hits == 0 and missed == ["雷A", "雷B"]


class TestLoadMines:
    def test_jsonl(self, tmp_path: Path) -> None:
        path = tmp_path / "m.jsonl"
        path.write_text(
            '{"transcript": "t01.md", "mines": [{"name": "雷", "wrong": "错说法", "correct": "对说法"}]}\n'
            "\n"
            '{"transcript": "t02.md", "mines": []}\n',
            encoding="utf-8",
        )
        cases = load_mines(path)
        assert len(cases) == 2
        assert cases[0].mines[0].wrong == "错说法"
        assert cases[0].mines[0].correct == "对说法"


def _strict_judge(report: str, mines: list[Mine]) -> tuple[int, list[str]]:
    """测试用假裁判：报告含"挖出:<雷名>"算命中——语义版的罐头。"""
    hits = sum(1 for m in mines if f"挖出:{m.name}" in report)
    return hits, [m.name for m in mines if f"挖出:{m.name}" not in report]


class TestRunAblation:
    def test_matrix_and_aggregation(self) -> None:
        """2 配置 × 1 稿 × 2 遍 = 4 次；full 全中、no-kb 全不中 → 100% vs 0%。"""
        canned = {"full": "挖出:雷A 挖出:雷B", "no-kb": "啥也没挖到"}

        def fake_run(_name: str, config: str) -> str:
            return canned[config]

        results = run_ablation([CASE], fake_run, _strict_judge, configs=("full", "no-kb"), runs=2)
        assert len(results) == 4
        text = format_ablation(results)
        assert "full: 100.0%" in text
        assert "no-kb: 0.0%" in text

    def test_black_box_records_run_report_and_missed(self) -> None:
        """汇总表之外还要留现场：第几遍、报告原文、漏了哪颗雷。"""
        reports = iter(["挖出:雷A", "挖出:雷A 挖出:雷B"])
        results = run_ablation(
            [CASE], lambda _n, _c: next(reports), _strict_judge, configs=("full",), runs=2
        )
        assert [r.run for r in results] == [1, 2]
        assert results[0].report == "挖出:雷A"
        assert results[0].missed == ["雷B"]
        assert results[1].missed == []
        assert all(r.error is None for r in results)

    def test_failed_run_excluded_but_counted(self) -> None:
        """翻车（诊断或判卷炸了）不计入命中率，但要如实报告翻车次数。"""
        def flaky(_name: str, _config: str) -> str:
            raise RuntimeError("诊断未完成")

        results = run_ablation([CASE], flaky, _strict_judge, configs=("full",), runs=2)
        assert all(not r.ok for r in results)
        assert all(r.error == "RuntimeError: 诊断未完成" for r in results)
        assert all(r.report == "" for r in results)  # 诊断没产出，报告留空而不是编内容
        assert "全部失败" in format_ablation(results)

    def test_judge_crash_marks_run_failed(self) -> None:
        """裁判自己抛异常也算这次翻车——坏判卷不能进统计。"""
        def bad_judge(_r: str, _m: list[Mine]) -> tuple[int, list[str]]:
            raise RuntimeError("裁判中暑了")

        results = run_ablation([CASE], lambda _n, _c: "报告", bad_judge, configs=("full",), runs=1)
        assert results[0].ok is False
        assert results[0].report == "报告"  # 诊断已完成，判卷翻车也不能把报告现场扔掉
        assert results[0].error == "RuntimeError: 裁判中暑了"

    def test_variance_visible(self) -> None:
        """同一配置两遍结果不同 → 标准差 > 0，方差是诚实的一部分。"""
        reports = iter(["挖出:雷A", "啥也没挖到"])

        def unstable(_n: str, _c: str) -> str:
            return next(reports)

        results = run_ablation([CASE], unstable, _strict_judge, configs=("full",), runs=2)
        # 命中率 1/2 和 0/2 → 均值 25%，标准差 25%
        assert "25.0% ± 25.0%" in format_ablation(results)


class TestWriteRunLog:
    def test_jsonl_round_trip(self, tmp_path: Path) -> None:
        """一行一次运行，中文报告与漏网雷可读；旧实验记录不会混进来。"""
        results = run_ablation(
            [CASE], lambda _n, _c: "挖出:雷A", _strict_judge, configs=("full",), runs=2
        )
        path = tmp_path / "nested" / "run-log.jsonl"
        path.parent.mkdir()
        path.write_text("旧实验\n", encoding="utf-8")
        write_run_log(results, path)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["config"] == "full" and first["case"] == "t01.md"
        assert first["run"] == 1 and first["missed"] == ["雷B"]
        assert first["report"] == "挖出:雷A" and first["error"] is None


class TestDiagnoseAblationSwitches:
    """diagnose 的两个消融开关：FakeProvider 看 system prompt 和工具表。"""

    def _run(self, tmp_path: Path, **kwargs: Any) -> FakeProvider:
        transcript = tmp_path / "t.md"
        transcript.write_text("面试官：好\n候选人：好", encoding="utf-8")
        provider = FakeProvider([FakeProvider.text_turn("诊断报告")])
        engine = QueryEngine(
            EngineConfig(provider=provider, retry=RetryConfig(base_delay=0.01), sleep=lambda s: None)
        )
        diagnose(transcript, engine, tmp_path / "none.db", **kwargs)
        return provider

    def _script_of(self, provider: FakeProvider) -> str:
        return provider.calls[0][0].content  # 第一次调用的第一条消息 = system prompt

    def test_full_config_keeps_three_step_script(self, tmp_path: Path) -> None:
        script = self._script_of(self._run(tmp_path))
        assert "三个工具" in script and "query_knowledge_base" in script

    def test_no_kb_rewrites_script_and_removes_tool(self, tmp_path: Path) -> None:
        provider = self._run(tmp_path, ablate_kb=True)
        script = self._script_of(provider)
        assert "两个工具" in script
        assert "query_knowledge_base" not in script  # 剧本不提检索，模型就不会幻觉调用
        registry = default_registry  # 工具摘除走 unregister，单测在下面
        assert registry  # 占位防误删

    def test_no_script_leaves_only_identity(self, tmp_path: Path) -> None:
        script = self._script_of(self._run(tmp_path, ablate_script=True))
        assert "流程" not in script and "工具" not in script
        assert "面试官" in script


class TestUnregister:
    def test_unregister_removes_tool(self, tmp_path: Path) -> None:
        engine = QueryEngine(EngineConfig(provider=FakeProvider([FakeProvider.text_turn("x")])))
        registry = default_registry(engine, tmp_path / "x.db")
        names = [s["name"] for s in registry.schemas()]
        assert "query_knowledge_base" in names
        registry.unregister("query_knowledge_base")
        names = [s["name"] for s in registry.schemas()]
        assert "query_knowledge_base" not in names
        assert len(names) == 2  # analyze + report 还在
