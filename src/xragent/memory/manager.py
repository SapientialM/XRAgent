"""MemoryManager：短期消息 + 长期 SQLite 事实。"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

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
    # 3. (source_turn) index supports future per-turn audit/revert queries
    #    (e.g. "list all facts saved by turn t1" or "delete facts by turn").
    #    The current API never queries by source_turn, but the column is
    #    populated on every save_fact() and the index is cheap; it removes
    #    a full scan if that pattern emerges.
    # 4. Old single-column idx_facts_category is a prefix of the composite and is
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
    CREATE INDEX IF NOT EXISTS idx_facts_source_turn ON facts(source_turn);
    """

    def __init__(self, db_path: Path | None = None):
        s = get_settings()
        self.db_path = db_path or s.memory_db
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        # PRAGMA 必须在 CREATE TABLE 之前: SQLite 允许中途切换,但 WAL 在
        # 第一次写入时就锁定, 先设更安全。两项都是 SQLite 长期记忆场景
        # 的标准优化:
        #   - journal_mode=WAL     读写不阻塞, N 个 recall 不再互锁 save
        #   - synchronous=NORMAL   WAL 模式下仍耐崩溃, 但省掉每次 commit 的 fsync
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
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

    def recall_range(
        self,
        start_ts: float | None = None,
        end_ts: float | None = None,
        category: str | None = None,
        k: int = 1000,
    ) -> list[Fact]:
        """按 ts 区间召回 fact。start_ts/end_ts 为 None 时分别表示 -∞ / +∞。

        与 recall() 的区别: recall() 走 LIKE 关键词路径, 本方法走时间窗口路径;
        两者互补, 一个回答"说过什么", 一个回答"什么时候说的"。

        索引命中:
          - 仅 ts 范围    -> idx_facts_ts
          - ts + category  -> idx_facts_category_ts
        ORDER BY ts DESC 让 LIMIT 提前结束。
        """
        sql = "SELECT id, ts, category, content, source_turn FROM facts"
        clauses: list[str] = []
        params: list = []
        if start_ts is not None:
            clauses.append("ts >= ?")
            params.append(start_ts)
        if end_ts is not None:
            clauses.append("ts <= ?")
            params.append(end_ts)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(k)
        rows = self._conn.execute(sql, params).fetchall()
        return [Fact(id=r[0], ts=r[1], category=r[2], content=r[3], source_turn=r[4]) for r in rows]

    def top_frequent(
        self,
        n: int = 10,
        category: str | None = None,
        min_count: int = 2,
    ) -> list[tuple[str, int]]:
        """按 content 出现次数降序，返回 top-N (content, count) 列表。

        用于回答"用户反复说过的点是什么" —— 单次出现的事实在 min_count=2 默认下
        会被过滤, 避免 top-N 永远被一次性噪音占满。需召回全部时显式传 min_count=1。

        同 content 在不同 category 下分别计数（GROUP BY 不跨类）。
        """
        sql = "SELECT content, COUNT(*) AS c FROM facts"
        params: list = []
        if category:
            sql += " WHERE category = ?"
            params.append(category)
        sql += " GROUP BY content HAVING c >= ? ORDER BY c DESC, MAX(ts) DESC LIMIT ?"
        params.extend([min_count, n])
        rows = self._conn.execute(sql, params).fetchall()
        return [(r[0], r[1]) for r in rows]

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