"""MemoryManager：短期消息 + 长期 SQLite 事实。"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..config.settings import get_settings


@dataclass
class Fact:
    id: int
    ts: float
    category: str
    content: str
    source_turn: str


class MemoryManager:
    # Schema notes:
    # 1. (category, ts DESC) composite index covers recall()'s two main patterns:
    #      WHERE category = ? ORDER BY ts DESC LIMIT ?
    #      WHERE category = ? AND content LIKE ? ORDER BY ts DESC LIMIT ?
    #    Filters by category AND keeps ts DESC ordering, so LIMIT can short-circuit.
    # 2. (ts DESC) alone kept for recent() and category-less recall().
    # 3. Old single-column idx_facts_category is a prefix of the composite and is
    #    therefore redundant; existing DBs may still carry it (harmless).
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS facts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts REAL NOT NULL,
      category TEXT NOT NULL,
      content TEXT NOT NULL,
      source_turn TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_facts_category_ts ON facts(category, ts DESC);
    CREATE INDEX IF NOT EXISTS idx_facts_ts ON facts(ts DESC);
    """

    def __init__(self, db_path: Path | None = None):
        s = get_settings()
        self.db_path = db_path or s.memory_db
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()

    def save_fact(self, category: str, content: str, source_turn: str = "") -> int:
        cur = self._conn.execute(
            "INSERT INTO facts (ts, category, content, source_turn) VALUES (?, ?, ?, ?)",
            (time.time(), category, content, source_turn),
        )
        self._conn.commit()
        return cur.lastrowid or 0

    def recall(self, query: str, k: int = 5, category: str | None = None) -> list[Fact]:
        sql = "SELECT id, ts, category, content, source_turn FROM facts"
        clauses = []
        params = []
        if query:
            clauses.append("content LIKE ?")
            params.append(f"%{query}%")
        if category:
            clauses.append("category = ?")
            params.append(category)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(k)
        rows = self._conn.execute(sql, params).fetchall()
        return [Fact(id=r[0], ts=r[1], category=r[2], content=r[3], source_turn=r[4]) for r in rows]

    def recent(self, n: int = 20) -> list[Fact]:
        rows = self._conn.execute(
            "SELECT id, ts, category, content, source_turn FROM facts ORDER BY ts DESC LIMIT ?", (n,)
        ).fetchall()
        return [Fact(id=r[0], ts=r[1], category=r[2], content=r[3], source_turn=r[4]) for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    def close(self) -> None:
        self._conn.close()

    def compress_if_needed(self, messages: list, budget_tokens: int, target_ratio: float = 0.7) -> list:
        from ..compression.simple import SimpleCompression
        return SimpleCompression(budget_tokens=budget_tokens, target_ratio=target_ratio).compress(messages)
