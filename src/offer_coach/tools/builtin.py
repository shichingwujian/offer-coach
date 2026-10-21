"""三个内置工具（D5：query_knowledge_base 已换内脏——从种子题换成 SQLite FTS5 真库）。

- query_knowledge_base：纯检索，查 FTS5 倒排索引（工厂函数焊 db_path，与焊 engine 同手法）
- analyze_content：LLM 工具——内部调 engine.query 让模型按评分维度分析
- generate_report：纯 Python 模板——排版是确定性活，不烧钱给模型干
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from offer_coach.engine.engine import QueryEngine
from offer_coach.engine.models import Message
from offer_coach.knowledge.db import RetrievalMode, search_for_diagnosis
from offer_coach.knowledge.embedder import Embedder
from offer_coach.knowledge.reranker import Reranker
from offer_coach.tools.registry import ToolDef, ToolRegistry


def make_query_knowledge_base(
    db_path: Path,
    *,
    retrieval_mode: RetrievalMode = "auto",
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
) -> Callable[[str], str]:
    """工厂函数：造出一个"焊死数据库路径"的查库工具。模型只需要填关键词。"""

    def query_knowledge_base(keyword: str) -> str:
        result = search_for_diagnosis(
            db_path, keyword, mode=retrieval_mode, embedder=embedder, reranker=reranker
        )
        mode_line = f"检索模式：{result.mode_used}"
        if result.fallback_reason:
            mode_line += f"（{result.fallback_reason}）"
        if not result.hits:
            return f"{mode_line}\n\n未找到与 '{keyword}' 相关的题目。"
        body = "\n\n".join(
            f"[{q.category}] {q.title}\n{q.body}" for q in result.hits
        )
        return f"{mode_line}\n\n{body}"

    return query_knowledge_base


# 四个评分维度（D10：记忆插件也认这几个名字，单一事实源）
DIMENSIONS = ("技术准确性", "结构化表达", "回答深度", "沟通清晰度")

_ANALYZE_PROMPT = """你是一位资深技术面试官。请按以下四个维度分析这段面试回答，每个维度给 1-5 分并引用原文做证据。

严格只返回一个 JSON 对象（不要输出任何其他文字、不要用 markdown 围栏），格式：
{"技术准确性": 3, "结构化表达": 4, "回答深度": 2, "沟通清晰度": 4,
 "证据": {"技术准确性": "……", "结构化表达": "……", "回答深度": "……", "沟通清晰度": "……"},
 "总评": "一段话总评"}"""


def _parse_analysis(text: str) -> dict | None:
    """从模型输出里挖出评分 JSON：剥围栏、找花括号。挖不到返回 None（失败当数据）。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not all(dim in data for dim in DIMENSIONS):
        return None
    return data


def _render_analysis(data: dict) -> str:
    """把评分 JSON 渲染成可读文本。排版是确定性活，不烧钱给模型干（D4 原则）。

    渲染格式固定（"技术准确性：2/5"）——D10 的记忆插件靠这个格式解析分数。
    """
    lines = ["## 四维评分", ""]
    evidence = data.get("证据", {})
    for dim in DIMENSIONS:
        line = f"- {dim}：{data[dim]}/5"
        if note := evidence.get(dim):
            line += f" —— {note}"
        lines.append(line)
    if summary := data.get("总评"):
        lines += ["", f"**总评**：{summary}"]
    return "\n".join(lines)


def make_analyze_content(engine: QueryEngine) -> Callable[[str], str]:
    """工厂函数：造出一个"带着自己发动机"的 analyze_content 工具。

    v2（D10）：输出从自由文本升级为"JSON 评分 + 确定性渲染"——
    结构化结果才能被程序消费（记忆层、评估集都要读分数）。
    模型没按格式返回时兜底返回原文（失败当数据）。
    """

    def analyze_content(transcript: str) -> str:
        turn = engine.query([
            Message(role="system", content=_ANALYZE_PROMPT),
            Message(role="user", content=f"面试回答原文：\n{transcript}"),
        ])
        text = turn.message.content or ""
        data = _parse_analysis(text)
        if data is None:
            return text or "（模型未返回分析内容）"
        return _render_analysis(data)

    return analyze_content


def generate_report(analysis: str, candidate: str = "候选人") -> str:
    """把分析结果排成 Markdown 报告。纯模板，零 LLM 调用。"""
    return (
        f"# 面试诊断报告\n\n"
        f"**候选人**：{candidate}\n\n"
        f"## 分析结果\n\n{analysis}\n\n"
        f"---\n*由 offer-coach 生成*\n"
    )


def default_registry(
    engine: QueryEngine,
    db_path: Path,
    *,
    retrieval_mode: RetrievalMode = "auto",
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
) -> ToolRegistry:
    """装配三个工具的默认注册表。发动机和数据仓库都在此接入（开店前的装配）。"""
    registry = ToolRegistry()
    registry.register(ToolDef(
        name="query_knowledge_base",
        description="检索面试题库：按关键词查找相关面试题和参考回答。想找某知识点的题目时使用。",
        parameters={
            "type": "object",
            "properties": {"keyword": {"type": "string", "description": "检索关键词，至少 3 个字符，如 'Redis'、'持久化'"}},
            "required": ["keyword"],
        },
        func=make_query_knowledge_base(
            db_path, retrieval_mode=retrieval_mode, embedder=embedder, reranker=reranker
        ),
    ))
    registry.register(ToolDef(
        name="analyze_content",
        description="分析一段面试回答的质量：从技术准确性、结构化表达、深度、沟通四个维度打分并给出证据。",
        parameters={
            "type": "object",
            "properties": {"transcript": {"type": "string", "description": "面试回答原文"}},
            "required": ["transcript"],
        },
        func=make_analyze_content(engine),
    ))
    registry.register(ToolDef(
        name="generate_report",
        description="把分析结果排版成 Markdown 诊断报告。分析完成后用它出最终报告。",
        parameters={
            "type": "object",
            "properties": {
                "analysis": {"type": "string", "description": "analyze_content 的输出"},
                "candidate": {"type": "string", "description": "候选人称呼，可省略"},
            },
            "required": ["analysis"],
        },
        func=generate_report,
    ))
    return registry
