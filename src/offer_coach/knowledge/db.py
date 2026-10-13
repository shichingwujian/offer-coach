"""题库数据库：灌库（进货上架，一次性）+ 检索（查索引页，毫秒级）。

- build_db：遍历题库目录 → 解析 → 全量重建 FTS5 表（幂等：跑两遍结果一样）
- search_questions：MATCH 翻倒排索引，按 rank 相关度排队

FTS5 用 trigram 分词（3 字滑窗），解决中文没有空格、默认分词器切不动的问题。
注意：trigram 要求关键词至少 3 个字符才能命中（"Redis"可以，"锁"不行）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from offer_coach.knowledge.parser import Question, parse_file

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
