"""机制消融（D006 第二层 / D14）：标准化病人考试。

埋雷稿 = 预埋已知薄弱点的面试稿（病是已知的，答案捏在考官手里）。
对照组每次摘掉一层机制（题库工具 / 导演剧本），看薄弱点命中率掉多少——
"这层机制有什么用"不再靠嘴说，靠对照实验。

尺子 v2（2026-10-15）：LLM 裁判，替代 v1 的别名关键词匹配。
v1 的死因：别名词检测的是"提没提到话题"，不是"挖没挖出错误"——
报告夸候选人"就余弦相似度进行了深入交流"也算命中，三配置全 100% 没有区分度。
v2 裁判拿着每颗雷的标准答案（wrong=候选人的错误说法，correct=正确说法），
只认两件事：① 报告明确指出这个说法是错的 ② 报告给出了正确方向。
只聊话题不算，说"不对"但说不出正确说法也不算。

诚实声明：
- 裁判和考生是同一个模型（DeepSeek）——可能"自己人打分手松"。
  三把尺子同一个裁判，相对比较仍然公平；绝对值别当精确数字看。
- 判不出来一律算不中（fail-closed）：裁判输出解析失败、证据为空、
  雷名对不上，统统按不中算。宁可漏记，不可多记。

跑诊断和判卷都是注入的（DI 第 8、9 次）：测试喂罐头，真机喂真货，
评分逻辑因此可以离线测死。
"""

from __future__ import annotations

import json
import re
import statistics
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from offer_coach.engine.models import Message

if TYPE_CHECKING:
    from offer_coach.engine.engine import QueryEngine

# 三把对照：完整版 / 摘题库 / 摘剧本
CONFIGS = ("full", "no-kb", "no-script")

# 跑诊断的函数：（稿子文件名, 配置）→ 报告文本。真机注入真 diagnose，测试注入罐头
RunFn = Callable[[str, str], str]


class Mine(BaseModel):
    """一颗雷：已知薄弱点 + 标准答案。wrong/correct 是给裁判的判卷依据。"""

    name: str
    wrong: str  # 候选人在稿子里的错误说法（什么病）
    correct: str  # 正确说法（病该怎么治）


class AblationCase(BaseModel):
    """一份埋雷稿：transcript 是文件名，mines 是埋进去的雷。"""

    transcript: str
    mines: list[Mine]


class RunResult(BaseModel):
    """一次运行的完整黑匣子；ok=False 排除出命中率，但保留现场供解剖。"""

    config: str
    case: str
    hits: int
    total: int
    ok: bool = True
    run: int = 1  # 同一配置、同一稿子的第几遍，从 1 开始
    missed: list[str] = Field(default_factory=list)  # 裁判判漏的雷名
    report: str = ""  # 报告原文；判卷翻车时也尽量保留
    error: str | None = None  # 异常类型 + 原因；没翻车为 None


# 判卷的函数：（报告文本, 雷区清单）→ (命中数, 漏网雷名)。真机注入 LLM 裁判，测试注入假裁判
JudgeFn = Callable[[str, list[Mine]], tuple[int, list[str]]]


_JUDGE_PROMPT = """你是严格的评审。给你一份面试诊断报告和一份"雷区清单"（候选人答错的点）。

对每一颗雷，判断报告是否挖出了它。命中必须同时满足两个条件：
① 报告明确指出候选人的这个说法是错的（只引用原话、只聊相关话题都不算）
② 报告给出了正确方向（说"不对"但说不出哪里对，不算）

雷区清单（JSON）：
{mines}

待判报告：
{report}

只输出 JSON 数组，每颗雷一项，不要输出任何别的内容：
[{{"name": "雷的名字（必须和清单一字不差）", "hit": true或false, "evidence": "报告中满足两个条件的原话；没挖出则填空字符串"}}]"""


def make_judge(engine: QueryEngine) -> JudgeFn:
    """真裁判：LLM 拿评分细则判卷（粒度 = 一份报告一次调用，所有雷一起判）。

    判不出来 = 不中：解析失败 / 雷名对不上 / 声称命中但证据为空，一律按不中算。
    方向是故意偏保守的——漏记只是低估命中率，多记会让消融对比失效。
    """

    def judge(report: str, mines: list[Mine]) -> tuple[int, list[str]]:
        mines_json = json.dumps([m.model_dump() for m in mines], ensure_ascii=False, indent=2)
        turn = engine.query(
            [Message(role="user", content=_JUDGE_PROMPT.format(mines=mines_json, report=report))]
        )
        verdicts = _parse_judgments(turn.message.content or "", mines)
        hits = sum(1 for m in mines if verdicts.get(m.name))
        missed = [m.name for m in mines if not verdicts.get(m.name)]
        return hits, missed

    return judge


def _parse_judgments(text: str, mines: list[Mine]) -> dict[str, bool]:
    """解析裁判输出为 {雷名: 中不中}。fail-closed：任何一步对不上，该雷不中。"""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, list):
        return {}
    valid_names = {m.name for m in mines}
    verdicts: dict[str, bool] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if name not in valid_names:
            continue  # 裁判编了清单外的雷名：不认识的直接扔
        # 命中必须带证据原话——空口说"挖到了"不算
        verdicts[name] = bool(item.get("hit")) and bool(str(item.get("evidence") or "").strip())
    return verdicts


def load_mines(path: Path) -> list[AblationCase]:
    """读雷区地图（JSONL，每行一个 case，跳过空行）。"""
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(AblationCase.model_validate_json(line))
    return cases


def run_ablation(
    cases: list[AblationCase],
    run_fn: RunFn,
    judge_fn: JudgeFn,
    configs: tuple[str, ...] = CONFIGS,
    runs: int = 2,
) -> list[RunResult]:
    """全矩阵跑一遍：配置 × 稿子 × 重复次数。LLM 有随机性，重复跑才能看方差。"""
    results = []
    for config in configs:
        for case in cases:
            for run_index in range(1, runs + 1):
                report = ""
                try:
                    report = run_fn(case.transcript, config)
                    hits, missed = judge_fn(report, case.mines)
                    results.append(RunResult(
                        config=config, case=case.transcript, hits=hits, total=len(case.mines),
                        run=run_index, missed=missed, report=report,
                    ))
                except Exception as e:
                    # 诊断或判卷中途翻车：排除出命中率，但保留异常和已有报告供解剖
                    results.append(RunResult(
                        config=config, case=case.transcript, hits=0, total=len(case.mines),
                        ok=False, run=run_index, report=report,
                        error=f"{type(e).__name__}: {e}",
                    ))
    return results


def write_run_log(results: list[RunResult], path: Path) -> None:
    """把每次运行写成一行 JSON。每次实验覆盖旧档，避免两轮数据混在一起。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.model_dump(), ensure_ascii=False) for r in results]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def format_ablation(results: list[RunResult]) -> str:
    """渲染对照表：每配置一行——命中率均值 ± 标准差（方差是诚实的一部分）。"""
    lines = ["配置对照（薄弱点命中率，均值 ± 标准差）："]
    for config in dict.fromkeys(r.config for r in results):  # 保持出现顺序
        group = [r for r in results if r.config == config]
        ok = [r for r in group if r.ok]
        rates = [r.hits / r.total for r in ok]
        if rates:
            mean = statistics.mean(rates)
            stdev = statistics.pstdev(rates) if len(rates) > 1 else 0.0
            line = f"- {config}: {mean:.1%} ± {stdev:.1%}（{len(rates)} 次有效）"
        else:
            line = f"- {config}: 全部失败"
        failed = len(group) - len(ok)
        if failed:
            line += f"，{failed} 次翻车未计入"
        lines.append(line)
    return "\n".join(lines)
