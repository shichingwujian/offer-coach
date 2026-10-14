"""Memory Store：跨会话记忆的档案柜（教程 06-context-memory 后半）。

Context（D7）管"这一次对话看什么"（桌面），Memory 管"跨多次对话记什么"（档案柜）。
存储继续用 SQLite——题库已经证明它够扛，不引入新基建。

克制原则（教程）：写太多 = 垃圾桶，召回变噪声。本层只提供货架，
"什么时候记"由 hooks.py 的死规则决定，不让模型自由发挥。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from pydantic import BaseModel

# 记忆类型（v1 三种）：画像 / 弱点档案 / 历次诊断摘要
# preference 有意不做——它需要"模型判断这句话值不值得记"，教程点名这是垃圾桶风险之源
MemoryType = str  # "user_profile" | "weak_point" | "diagnosis_summary"


class MemoryEntry(BaseModel):
    """一条记忆。confidence = 坐实度：反复出现才升，召回只信高坐实度的。"""

    id: str
    type: MemoryType
    key: str  # 语义标识：弱点用维度名，画像固定 "main"
    value: dict  # 结构化数据，落库时 JSON 序列化
    confidence: float = 0.5  # 新生 0.5；同 key 再出现 +0.1，封顶 1.0
    created_at: str = ""
    updated_at: str = ""
    access_count: int = 0  # 被召回次数（观察"哪些记忆真有用"）


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    access_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_memories_type_key ON memories(type, key);
"""


class MemoryStore:
    """档案柜本体：增、查、改。不做向量检索——那是混合召回冲刺的事。"""

    def __init__(self, db_path: Path) -> None:
        self._db = sqlite3.connect(str(db_path))
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)

    def create(self, type: MemoryType, key: str, value: dict) -> str:
        """新记一条。坐实度默认 0.5——"一次考砸是意外"，先观望。"""
        entry_id = f"{type}:{key}:{uuid.uuid4().hex[:8]}"
        self._db.execute(
            "INSERT INTO memories (id, type, key, value) VALUES (?, ?, ?, ?)",
            (entry_id, type, key, json.dumps(value, ensure_ascii=False)),
        )
        self._db.commit()
        return entry_id

    def retrieve(
        self,
        *,
        type: MemoryType | None = None,
        key: str | None = None,
        min_confidence: float | None = None,
        limit: int | None = None,
    ) -> list[MemoryEntry]:
        """按条件取记忆：坐实度高、最近更新的排前面。取过的记一笔 access_count。"""
        sql = "SELECT * FROM memories WHERE 1=1"
        params: list[object] = []
        if type is not None:
            sql += " AND type = ?"
            params.append(type)
        if key is not None:
            sql += " AND key = ?"
            params.append(key)
        if min_confidence is not None:
            sql += " AND confidence >= ?"
            params.append(min_confidence)
        sql += " ORDER BY confidence DESC, updated_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._db.execute(sql, params).fetchall()
        entries = []
        for row in rows:  # 记一笔"被取过"，返回的对象里本次也计入
            self._db.execute(
                "UPDATE memories SET access_count = access_count + 1 WHERE id = ?",
                (row["id"],),
            )
            entry = self._to_entry(row)
            entry.access_count += 1
            entries.append(entry)
        if entries:
            self._db.commit()
        return entries

    def update(self, entry_id: str, value: dict, *, boost: bool = False) -> None:
        """更新内容。boost=True 时坐实度 +0.1（封顶 1.0）——"又考砸了，坐实一点"。"""
        sql = "UPDATE memories SET value = ?, updated_at = datetime('now')"
        params: list[object] = [json.dumps(value, ensure_ascii=False)]
        if boost:
            sql += ", confidence = MIN(1.0, confidence + 0.1)"
        sql += " WHERE id = ?"
        params.append(entry_id)
        self._db.execute(sql, params)
        self._db.commit()

    def get_profile(self) -> dict:
        """用户画像（固定 key='main' 的那条）。没有就是空档案。"""
        entries = self.retrieve(type="user_profile", key="main")
        return entries[0].value if entries else {}

    def update_profile(self, patch: dict) -> None:
        """画像只 patch 不覆盖：老字段保留，新字段并入。"""
        existing = self.retrieve(type="user_profile", key="main")
        if existing:
            self.update(existing[0].id, {**existing[0].value, **patch})
        else:
            self.create("user_profile", "main", patch)

    def stats(self) -> dict:
        """柜子里有什么：总数 + 按类型分。"""
        total = self._db.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]
        by_type = {
            row["type"]: row["c"]
            for row in self._db.execute(
                "SELECT type, COUNT(*) AS c FROM memories GROUP BY type"
            ).fetchall()
        }
        return {"total": total, "by_type": by_type}

    @staticmethod
    def _to_entry(row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            id=row["id"],
            type=row["type"],
            key=row["key"],
            value=json.loads(row["value"]),
            confidence=row["confidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            access_count=row["access_count"],
        )
