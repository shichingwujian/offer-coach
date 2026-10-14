"""召回评估：先造尺子再造轮子（D006 第一层）。

评估集 = 一堆"查询 + 标准答案"（eval/recall_set.jsonl，三种查询类型：关键词/转述/场景）。
recall@k = 前 k 个结果里命中标准答案的比例——第 k+1 名以后等于不存在（只塞 top-k 给模型）。

检索函数是注入的（依赖注入第 6 次）：今天量纯 FTS5，明天量混合召回，
同一把尺子量出提升——"先造尺子再造轮子"就落在这个设计上。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from offer_coach.knowledge.parser import Question

SearchFn = Callable[[str], list[Question]]  # 被测的检索函数：查询 → 排好序的结果


class EvalCase(BaseModel):
    """一条评估用例：用户这么问时，该查到 expect 里的题（命中其一即算中）。"""

    query: str
    type: str  # keyword 关键词 | paraphrase 转述 | scenario 场景
    expect: list[str]  # 可接受的题目标题


class CaseResult(BaseModel):
    case: EvalCase
    hit: bool
    got: list[str]  # 实际返回的题目标题（前 k 个）


class EvalReport(BaseModel):
    k: int
    total: int
    hits: int
    recall: float
    by_type: dict[str, float]  # 分类型召回率——短板在哪一型，一目了然
    misses: list[CaseResult]  # 漏网清单：改进时的调试线索


def load_eval_set(path: Path) -> list[EvalCase]:
    """读 JSONL 评估集：每行 {"query", "type", "expect"}。"""
    return [
        EvalCase.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_recall(cases: list[EvalCase], search: SearchFn, *, k: int = 5) -> EvalReport:
    """逐条查询跑检索，算 recall@k。命中 = 前 k 个标题里出现任一标准答案。"""
    results: list[CaseResult] = []
    for case in cases:
        got = [q.title for q in search(case.query)][:k]
        results.append(CaseResult(case=case, hit=any(t in got for t in case.expect), got=got))
    hits = sum(r.hit for r in results)
    by_type = {
        t: sum(r.hit for r in results if r.case.type == t)
        / max(1, sum(1 for r in results if r.case.type == t))
        for t in {c.type for c in cases}
    }
    return EvalReport(
        k=k,
        total=len(results),
        hits=hits,
        recall=hits / len(results) if results else 0.0,
        by_type=by_type,
        misses=[r for r in results if not r.hit],
    )


def format_report(report: EvalReport) -> str:
    """把报告排成人看的文本：总数字 → 分类型 → 漏网清单（改进时的调试线索）。"""
    lines = [
        f"recall@{report.k} = {report.hits}/{report.total} = {report.recall:.1%}",
        "",
        "分类型：",
    ]
    lines += [f"- {t}: {v:.1%}" for t, v in sorted(report.by_type.items())]
    if report.misses:
        lines += ["", f"漏网（{len(report.misses)} 条）："]
        for r in report.misses:
            lines.append(f"- [{r.case.type}] {r.case.query}")
            lines.append(f"  期望：{' / '.join(r.case.expect)}")
            lines.append(f"  实际：{' / '.join(r.got) or '（无结果）'}")
    return "\n".join(lines)
