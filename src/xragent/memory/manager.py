"""MemoryManager: 短期消息 + 长期 SQLite 事实。"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config.settings import get_settings


@dataclass
class Fact:
    id: int
    ts: float
    category: str
    content: str
    source_turn: str
    # 5.1: source_turn_idx INTEGER nullable
    source_turn_idx: int | None = None
    # 5.3: priority
    priority: int = 0
    # 5.4: tags JSON
    tags: list[str] = field(default_factory=list)
    # 5.5: archived 软删除标记
    archived: bool = False
    # 5.6: title 短标签
    title: str | None = None


class MemoryManager:
    # Schema 演化注记:
    # 5.0 -> 5.1: facts +source_turn_idx; +idx_facts_source_turn_idx; +recall_by_turn_idx
    # 5.1 -> 5.2: +delete_by_turn_idx
    # 5.2 -> 5.3: +priority NOT NULL DEFAULT 0; +idx_facts_category_priority_ts; +recall_high_priority
    # 5.3 -> 5.4: +tags TEXT DEFAULT '[]'; +idx_facts_tags; +recall_by_tag
    # 5.4 -> 5.5: +archived NOT NULL DEFAULT 0; +partial idx_facts_active; +archive/unarchive/recall_active/count_active
    # 5.5 -> 5.6: facts +title TEXT nullable; +idx_facts_title; Fact +title: str|None=None
    #   +save_fact +title; +recall_by_title(title,k); +update_title(fact_id,new_title) -> Fact|None
    # 5.6 idx 理由: recall_by_title WHERE title = ? ORDER BY ts DESC LIMIT k
    #   title 稀疏 (大量 NULL), 独立 B-tree 索引只覆盖非 NULL 行 (SQLite NULL 默认不入),
    #   索引体积约等于已命名行数, 不膨胀。partial index 不必要。
    # 5.6 兼容: save_fact 不传 title 仍合法; Fact 构造不传 title 仍合法; SELECT/INSERT 增量扩展。

    BASE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS facts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts REAL NOT NULL,
      category TEXT NOT NULL,
      content TEXT NOT NULL,
      source_turn TEXT,
      source_turn_idx INTEGER,
      priority INTEGER NOT NULL DEFAULT 0,
      tags TEXT DEFAULT '[]',
      archived INTEGER NOT NULL DEFAULT 0,
      title TEXT
    );
    """

    INDEX_SCHEMA = """
    CREATE INDEX IF NOT EXISTS idx_facts_category_ts ON facts(category, ts DESC);
    CREATE INDEX IF NOT EXISTS idx_facts_ts ON facts(ts DESC);
    CREATE INDEX IF NOT EXISTS idx_facts_source_turn ON facts(source_turn);
    CREATE INDEX IF NOT EXISTS idx_facts_source_turn_idx ON facts(source_turn_idx);
    CREATE INDEX IF NOT EXISTS idx_facts_category_priority_ts ON facts(category, priority DESC, ts DESC);
    CREATE INDEX IF NOT EXISTS idx_facts_tags ON facts(tags);
    CREATE INDEX IF NOT EXISTS idx_facts_active ON facts(ts DESC) WHERE archived = 0;
    CREATE INDEX IF NOT EXISTS idx_facts_title ON facts(title);
    """

    SCHEMA = BASE_SCHEMA + INDEX_SCHEMA

    _FACT_COLUMNS = (
        "id", "ts", "category", "content", "source_turn",
        "source_turn_idx", "priority", "tags", "archived", "title",
    )
    _FACT_COLS_SQL = ", ".join(_FACT_COLUMNS)

    @staticmethod
    def _decode_tags(raw):
        if not raw:
            return []
        try:
            v = json.loads(raw)
            return [str(x) for x in v] if isinstance(v, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def _encode_tags(tags):
        if tags is None:
            return "[]"
        try:
            return json.dumps(list(tags), ensure_ascii=False)
        except (TypeError, ValueError):
            return "[]"

    @staticmethod
    def _row_to_fact(row):
        return Fact(
            id=row[0],
            ts=row[1],
            category=row[2],
            content=row[3],
            source_turn=row[4],
            source_turn_idx=row[5],
            priority=row[6],
            tags=MemoryManager._decode_tags(row[7]),
            archived=bool(row[8]),
            title=row[9],
        )

    def __init__(self, db_path=None):
        s = get_settings()
        self.db_path = db_path or s.memory_db
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(self.BASE_SCHEMA)
        self._migrate_v51()
        self._migrate_v53()
        self._migrate_v54()
        self._migrate_v55()
        self._migrate_v56()
        self._conn.executescript(self.INDEX_SCHEMA)
        self._conn.commit()

    def _migrate_v51(self):
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "source_turn_idx" not in cols:
            self._conn.execute("ALTER TABLE facts ADD COLUMN source_turn_idx INTEGER")
            self._conn.commit()

    def _migrate_v53(self):
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "priority" in cols:
            return
        self._conn.execute(
            "ALTER TABLE facts ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
        )
        self._conn.execute("UPDATE facts SET priority = 0 WHERE priority IS NULL")
        self._conn.commit()

    def _migrate_v54(self):
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "tags" in cols:
            return
        self._conn.execute("ALTER TABLE facts ADD COLUMN tags TEXT DEFAULT '[]'")
        self._conn.execute("UPDATE facts SET tags = '[]' WHERE tags IS NULL")
        self._conn.commit()

    def _migrate_v55(self):
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "archived" in cols:
            return
        self._conn.execute(
            "ALTER TABLE facts ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
        )
        self._conn.execute("UPDATE facts SET archived = 0 WHERE archived IS NULL")
        self._conn.commit()

    def _migrate_v56(self):
        """5.5 -> 5.6: 补 title 列 (nullable TEXT). 老行 title=NULL=未命名, 行为不变."""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "title" in cols:
            return
        self._conn.execute("ALTER TABLE facts ADD COLUMN title TEXT")
        self._conn.commit()

    def save_fact(
        self,
        category,
        content,
        source_turn="",
        source_turn_idx=None,
        priority=0,
        tags=None,
        title=None,
    ):
        """5.6 新增 title 参数 (默认 None). 旧调用方不传仍合法."""
        ts = time.time()
        tags_json = self._encode_tags(tags)
        cur = self._conn.execute(
            "INSERT INTO facts "
            "(ts, category, content, source_turn, source_turn_idx, priority, tags, archived, title) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (ts, category, content, source_turn, source_turn_idx, priority, tags_json, title),
        )
        self._conn.commit()
        new_id = cur.lastrowid or 0
        return Fact(
            id=new_id, ts=ts, category=category, content=content,
            source_turn=source_turn, source_turn_idx=source_turn_idx,
            priority=priority,
            tags=list(tags) if tags else [],
            archived=False,
            title=title,
        )

    def recall(self, query, k=5, category=None):
        sql = f"SELECT {self._FACT_COLS_SQL} FROM facts"
        clauses, params = [], []
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
        return [self._row_to_fact(r) for r in rows]

    def recall_range(self, start_ts=None, end_ts=None, category=None, k=1000):
        sql = f"SELECT {self._FACT_COLS_SQL} FROM facts"
        clauses, params = [], []
        if start_ts is not None:
            clauses.append("ts >= ?"); params.append(start_ts)
        if end_ts is not None:
            clauses.append("ts <= ?"); params.append(end_ts)
        if category:
            clauses.append("category = ?"); params.append(category)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(k)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def top_frequent(self, n=10, category=None, min_count=2):
        sql = "SELECT content, COUNT(*) AS c FROM facts"
        params = []
        if category:
            sql += " WHERE category = ?"; params.append(category)
        sql += " GROUP BY content HAVING c >= ? ORDER BY c DESC, MAX(ts) DESC LIMIT ?"
        params.extend([min_count, n])
        rows = self._conn.execute(sql, params).fetchall()
        return [(r[0], r[1]) for r in rows]

    def recall_by_turn_idx(self, turn_idx, k=100):
        rows = self._conn.execute(
            f"SELECT {self._FACT_COLS_SQL} FROM facts "
            "WHERE source_turn_idx = ? ORDER BY ts DESC LIMIT ?",
            (turn_idx, k),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def delete_by_turn_idx(self, turn_idx):
        cur = self._conn.execute(
            "DELETE FROM facts WHERE source_turn_idx = ?", (turn_idx,)
        )
        self._conn.commit()
        return cur.rowcount

    def recall_high_priority(self, k=10, category=None, min_priority=1):
        sql = f"SELECT {self._FACT_COLS_SQL} FROM facts WHERE priority >= ?"
        params = [min_priority]
        if category:
            sql += " AND category = ?"; params.append(category)
        sql += " ORDER BY priority DESC, ts DESC LIMIT ?"
        params.append(k)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def recall_by_tag(self, tag, k=10):
        if not tag:
            return []
        sql = (
            f"SELECT {self._FACT_COLS_SQL} FROM facts WHERE tags LIKE ? "
            "ORDER BY ts DESC LIMIT ?"
        )
        rows = self._conn.execute(sql, (f'%"{tag}"%', k)).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def recall_by_title(self, title, k=10):
        """5.6 新方法: 按 title 精确匹配召回 (走 idx_facts_title)."""
        if not title:
            return []
        rows = self._conn.execute(
            f"SELECT {self._FACT_COLS_SQL} FROM facts "
            "WHERE title = ? ORDER BY ts DESC LIMIT ?",
            (title, k),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def update_title(self, fact_id, new_title):
        """5.6 新方法: 更新 title 并返回更新后的 Fact | None.

        返回类型 Fact | None (None = id 不存在 / rowcount=0).
        与 archive_fact (返回 bool) 不同: 这里回填完整 Fact, 避免二次 recall 开销.
        new_title=None 表示清空 title.
        """
        cur = self._conn.execute(
            "UPDATE facts SET title = ? WHERE id = ?", (new_title, fact_id)
        )
        self._conn.commit()
        if cur.rowcount == 0:
            return None
        rows = self._conn.execute(
            f"SELECT {self._FACT_COLS_SQL} FROM facts WHERE id = ?", (fact_id,)
        ).fetchall()
        if not rows:
            return None
        return self._row_to_fact(rows[0])

    def recent(self, n=20):
        rows = self._conn.execute(
            f"SELECT {self._FACT_COLS_SQL} FROM facts ORDER BY ts DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def archive_fact(self, fact_id):
        cur = self._conn.execute(
            "UPDATE facts SET archived = 1 WHERE id = ? AND archived = 0",
            (fact_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def unarchive_fact(self, fact_id):
        cur = self._conn.execute(
            "UPDATE facts SET archived = 0 WHERE id = ? AND archived = 1",
            (fact_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def recall_active(self, query="", k=10, category=None):
        sql = f"SELECT {self._FACT_COLS_SQL} FROM facts WHERE archived = 0"
        clauses, params = [], []
        if query:
            clauses.append("content LIKE ?")
            params.append(f"%{query}%")
        if category:
            clauses.append("category = ?")
            params.append(category)
        if clauses:
            sql += " AND " + " AND ".join(clauses)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(k)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def count_active(self):
        return self._conn.execute(
            "SELECT COUNT(*) FROM facts WHERE archived = 0"
        ).fetchone()[0]

    def count(self):
        return self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    def close(self):
        self._conn.close()

    def compress_if_needed(self, messages, budget_tokens, target_ratio=0.7):
        from ..compression.simple import SimpleCompression
        return SimpleCompression(
            budget_tokens=budget_tokens, target_ratio=target_ratio
        ).compress(messages)