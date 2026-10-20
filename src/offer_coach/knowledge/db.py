"""题库数据库：灌库（进货上架，一次性）+ 检索（查索引页，毫秒级）。

- build_db：遍历题库目录 → 解析 → 全量重建 FTS5 表（幂等：跑两遍结果一样）
- search_questions：MATCH 翻倒排索引，按 rank 相关度排队
- search_smart（D12）：拆词 → 每词各查 → 加权合并
- build_vectors / search_vectors / search_hybrid（D13）：语义坐标 + RRF 融合

FTS5 用 trigram 分词（3 字滑窗），解决中文没有空格、默认分词器切不动的问题。
注意：trigram 要求关键词至少 3 个字符才能命中（"Redis"可以，"锁"不行）。
"""

from __future__ import annotations

import sqlite3
from array import array
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from offer_coach.knowledge.embedder import Embedder, cosine
from offer_coach.knowledge.parser import Question, parse_file
from offer_coach.knowledge.preprocess import extract_terms

RetrievalMode = Literal["auto", "phrase", "terms", "hybrid"]
RetrievalChannel = Literal["phrase", "terms", "hybrid"]


class RetrievalResult(BaseModel):
    """一次检索的结果和真实路径；mode_used 不能说谎，fallback 要留原因。"""

    hits: list[Question]
    mode_used: RetrievalChannel
    fallback_reason: str | None = None

_SCHEMA = """
CREATE VIRTUAL TABLE questions USING fts5(
    title, body, category,
    tokenize = 'trigram'
)
"""


def build_db(source_dir: Path, db_path: Path) -> int:
    """把题库目录灌进 SQLite。全量重建，返回灌入的题目数。"""
    if db_path.exists():
        db_path.unlink()  # 重建：先删旧库，保证跑两遍结果一样（幂等）

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_SCHEMA)
        count = 0
        for category_dir in sorted(source_dir.iterdir()):
            md = category_dir / "index.md"
            if not category_dir.is_dir() or not md.exists():
                continue
            for q in parse_file(md, category_dir.name):
                conn.execute(
                    "INSERT INTO questions (title, body, category) VALUES (?, ?, ?)",
                    (q.title, q.body, q.category),
                )
                count += 1
        conn.commit()
        return count
    finally:
        conn.close()


def search_questions(db_path: Path, keyword: str, limit: int = 5) -> list[Question]:
    """按关键词查题库，按相关度排队，最多返回 limit 条。库不存在 = 明确报错。"""
    if not db_path.exists():
        raise FileNotFoundError(f"题库不存在：{db_path}。请先运行 offer-coach ingest <题库目录>")
    conn = sqlite3.connect(db_path)
    try:
        if len(keyword) >= 3:
            # 正常路径：MATCH 翻倒排索引。双引号包住，防特殊字符被当成 MATCH 语法
            query = '"' + keyword.replace('"', '""') + '"'
            rows = conn.execute(
                "SELECT title, body, category FROM questions "
                "WHERE questions MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
        else:
            # 短关键词兜底：trigram 索引没有不足 3 字的词，退化为 LIKE 逐行扫（384 行，瞬间完成）
            like = f"%{keyword}%"
            rows = conn.execute(
                "SELECT title, body, category FROM questions "
                "WHERE title LIKE ? OR body LIKE ? LIMIT ?",
                (like, like, limit),
            ).fetchall()
        return [Question(category=r[2], title=r[0], body=r[1]) for r in rows]
    finally:
        conn.close()


def search_smart(db_path: Path, query: str, limit: int = 5) -> list[Question]:
    """D12 拆词检索：拆词 → 每词各查一遍 → 按加权分合并排序（词与词是 OR 关系）。

    合并规则：标题命中记 2 分、正文命中记 1 分（标题是题目主旨，权重高）；
    同分比各自查询里的最佳名次。每词取 limit*4 条进合并池——
    高频词（如"工具"）的 LIKE 池按写入顺序返回，池小了目标题可能压根没进池。
    search_questions 本身一行不动——基线留着做对照。
    """
    terms = extract_terms(query)
    if not terms:  # 整句全是废话词，没有肉
        return []
    hits: dict[str, list] = {}  # title -> [加权分, 最佳名次, Question]
    for term in terms:
        for rank, q in enumerate(search_questions(db_path, term, limit=limit * 4)):
            entry = hits.setdefault(q.title, [0, rank, q])
            entry[0] += 2 if term in q.title else 1
            entry[1] = min(entry[1], rank)
    ranked = sorted(hits.values(), key=lambda e: (-e[0], e[1]))
    return [entry[2] for entry in ranked[:limit]]


# ---------------- D13：向量召回（语义通道） ----------------

_VEC_SCHEMA = """
CREATE TABLE IF NOT EXISTS question_vecs(
    title TEXT PRIMARY KEY,
    embedding BLOB
)
"""


def build_vectors(db_path: Path, embedder: Embedder) -> int:
    """给题库每道题算语义坐标，存进 question_vecs 表（一次性，可重复跑）。

    向量文本 = 标题 + 正文前 200 字：标题是主旨，正文前段给上下文。
    向量存 BLOB（float32 数组字节），807 题 × 512 维 ≈ 1.6MB，毫秒级读出。
    """
    if not db_path.exists():
        raise FileNotFoundError(f"题库不存在：{db_path}。请先运行 offer-coach ingest <题库目录>")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_VEC_SCHEMA)
        conn.execute("DELETE FROM question_vecs")  # 全量重建，和 build_db 一样幂等
        rows = conn.execute("SELECT title, body FROM questions").fetchall()
        texts = [f"{title}\n{body[:200]}" for title, body in rows]
        vectors = embedder.embed(texts)
        for (title, _), vec in zip(rows, vectors):
            conn.execute(
                "INSERT INTO question_vecs (title, embedding) VALUES (?, ?)",
                (title, array("f", vec).tobytes()),
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def has_vectors(db_path: Path) -> bool:
    """向量通道是否有货：表存在且有坐标才算可用。"""
    if not db_path.exists():
        raise FileNotFoundError(f"题库不存在：{db_path}。请先运行 offer-coach ingest <题库目录>")
    conn = sqlite3.connect(db_path)
    try:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='question_vecs'"
        ).fetchone()
        if not has_table:
            return False
        (count,) = conn.execute("SELECT COUNT(*) FROM question_vecs").fetchone()
        return count > 0
    finally:
        conn.close()


def search_vectors(
    db_path: Path, query: str, limit: int = 5, *, embedder: Embedder
) -> list[Question]:
    """语义通道：查询算坐标 → 和每道题的坐标比方向（余弦）→ 最像的排前面。

    向量表不存在（没跑过 build_vectors）→ 返回空，让调用方退化成纯字面检索。
    """
    if not db_path.exists():
        raise FileNotFoundError(f"题库不存在：{db_path}。请先运行 offer-coach ingest <题库目录>")
    conn = sqlite3.connect(db_path)
    try:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='question_vecs'"
        ).fetchone()
        if not has_table:
            return []  # 没建向量表：语义通道没货，不报错，静默退化
        rows = conn.execute(
            "SELECT q.title, q.body, q.category, v.embedding FROM questions q "
            "JOIN question_vecs v ON v.title = q.title"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return []
    (q_vec,) = embedder.embed([query])
    scored = []
    for title, body, category, blob in rows:
        vec = array("f")
        vec.frombytes(blob)
        scored.append((cosine(list(q_vec), list(vec)), Question(category=category, title=title, body=body)))
    scored.sort(key=lambda e: -e[0])  # 余弦越大越像，降序
    return [q for _, q in scored[:limit]]


def search_hybrid(
    db_path: Path, query: str, limit: int = 5, *, embedder: Embedder, k_rrf: int = 60
) -> list[Question]:
    """D13 混合召回：字面通道（拆词）+ 语义通道（向量）各查各的，RRF 融合。

    RRF（倒数名次融合）：两路的分数是两种货币没法比大小，但名次可比——
    每题得分 = Σ 1/(60 + 它在某榜的名次)。两榜都靠前的得分高，
    只在一榜靠前的也能活下来。
    """
    lexical = search_smart(db_path, query, limit=limit * 2)
    semantic = search_vectors(db_path, query, limit=limit * 2, embedder=embedder)
    scores: dict[str, list] = {}  # title -> [RRF 得分, Question]
    for board in (lexical, semantic):
        for rank, q in enumerate(board):
            entry = scores.setdefault(q.title, [0.0, q])
            entry[0] += 1.0 / (k_rrf + rank + 1)
    ranked = sorted(scores.values(), key=lambda e: -e[0])
    return [entry[1] for entry in ranked[:limit]]


def search_for_diagnosis(
    db_path: Path,
    query: str,
    limit: int = 5,
    *,
    mode: RetrievalMode = "auto",
    embedder: Embedder | None = None,
) -> RetrievalResult:
    """正式诊断的统一检索入口：请求一种模式，报告真实使用的路径。

    auto 的兜底原则是"增强能力缺失不拖垮诊断"：没有 embedder、没建向量索引、
    或向量通道加载失败时退回 terms，并把退化原因写进 RetrievalResult。
    """
    if mode == "phrase":
        return RetrievalResult(hits=search_questions(db_path, query, limit), mode_used="phrase")
    if mode == "terms":
        return RetrievalResult(hits=search_smart(db_path, query, limit), mode_used="terms")
    if mode not in ("auto", "hybrid"):
        raise ValueError(f"未知检索模式：{mode}")

    if embedder is None:
        return _terms_fallback(db_path, query, limit, "未提供向量模型")
    if not has_vectors(db_path):
        return _terms_fallback(db_path, query, limit, "未建向量索引")
    try:
        hits = search_hybrid(db_path, query, limit, embedder=embedder)
    except (ImportError, OSError, RuntimeError) as e:
        return _terms_fallback(
            db_path, query, limit, f"向量通道不可用：{type(e).__name__}: {e}"
        )
    return RetrievalResult(hits=hits, mode_used="hybrid")


def _terms_fallback(
    db_path: Path,
    query: str,
    limit: int,
    reason: str,
) -> RetrievalResult:
    """hybrid 不可用时的明确退化：结果可用，但路径不能伪装。"""
    return RetrievalResult(
        hits=search_smart(db_path, query, limit),
        mode_used="terms",
        fallback_reason=reason,
    )
