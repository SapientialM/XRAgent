"""MemoryManager：短期消息 + 长期 SQLite 事实。"""
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
    # 5.1: source_turn_idx INTEGER nullable; 末尾 + 默认 None, 老构造兼容
    source_turn_idx: int | None = None
    # 5.3: priority; recall_high_priority 用; 默认 0 = 未标重要级
    priority: int = 0
    # 5.4: tags JSON 数组; recall_by_tag 用; 默认 []
    tags: list[str] = field(default_factory=list)
    # 5.5: archived 布尔; 软删除标记; 默认 False = visible
    archived: bool = False


class MemoryManager:
    # === Schema 演化注记 ===
    # 5.0 → 5.1: facts +source_turn_idx; +idx_facts_source_turn_idx; recall_by_turn_idx
    # 5.1 → 5.2: +delete_by_turn_idx (复用 5.1 索引)
    # 5.2 → 5.3: facts +priority NOT NULL DEFAULT 0;
    #   +idx_facts_category_priority_ts(category, priority DESC, ts DESC);
    #   +recall_high_priority(k, category, min_priority); Fact +priority
    # 5.3 → 5.4: facts +tags TEXT DEFAULT '[]'; +idx_facts_tags;
    #   +recall_by_tag(tag, k); Fact +tags; save_fact +tags 参数
    # 5.4 → 5.5: facts +archived INTEGER NOT NULL DEFAULT 0;
    #   +partial idx_facts_active ON facts(ts DESC) WHERE archived = 0;
    #   +archive_fact / unarchive_fact / recall_active / count_active;
    #   Fact +archived: bool = False
    # 5.5 partial index 理由: recall_active() 主路径
    #   WHERE archived=0 ORDER BY ts DESC LIMIT k
    #   partial (ts DESC) WHERE archived=0 让 index seek + ORDER BY 零成本 + LIMIT 提前结束
    #   索引体积 ≈ active 行数, archived 行不进索引
    # 5.5 兼容: 现有 recall/recent/recall_range 不强制过滤 archived
    #   (archived 行仍可见, 调用方靠 Fact.archived 自行判断); recall_active 是显式入口

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
      archived INTEGER NOT NULL DEFAULT 0
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
    """

    # 兼容旧引用 (任何外部代码读 SCHEMA 仍可拿到完整脚本)
    SCHEMA = BASE_SCHEMA + INDEX_SCHEMA

    # SELECT 投影顺序契约: 所有 SELECT 按此顺序输出, _row_to_fact 用 fixed indices 还原
    # 5.5: 末尾追加 archived (0/1, bool() 转换)
    _FACT_COLUMNS = (
        "id", "ts", "category", "content", "source_turn",
        "source_turn_idx", "priority", "tags", "archived",
    )
    _FACT_COLS_SQL = ", ".join(_FACT_COLUMNS)

    @staticmethod
    def _decode_tags(raw: str | None) -> list[str]:
        """DB tags TEXT → list[str]。失败回退 []。"""
        if not raw:
            return []
        try:
            v = json.loads(raw)
            return [str(x) for x in v] if isinstance(v, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def _encode_tags(tags: list[str] | None) -> str:
        """list[str] → DB tags TEXT。None → '[]'。"""
        if tags is None:
            return "[]"
        try:
            return json.dumps(list(tags), ensure_ascii=False)
        except (TypeError, ValueError):
            return "[]"

    @staticmethod
    def _row_to_fact(row: tuple) -> Fact:
        """DB 行 → Fact。集中后改一处即可, 5.5 多读 row[8] = archived."""
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
        )

    def __init__(self, db_path: Path | None = None):
        s = get_settings()
        self.db_path = db_path or s.memory_db
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # 顺序: BASE_SCHEMA (新 DB 拿全列) -> 幂等 migration (老 DB 补列) -> 索引
        self._conn.executescript(self.BASE_SCHEMA)
        self._migrate_v51()
        self._migrate_v53()
        self._migrate_v54()
        self._migrate_v55()
        self._conn.executescript(self.INDEX_SCHEMA)
        self._conn.commit()

    def _migrate_v51(self) -> None:
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "source_turn_idx" not in cols:
            self._conn.execute("ALTER TABLE facts ADD COLUMN source_turn_idx INTEGER")
            self._conn.commit()

    def _migrate_v53(self) -> None:
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "priority" in cols:
            return
        self._conn.execute(
            "ALTER TABLE facts ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
        )
        self._conn.execute("UPDATE facts SET priority = 0 WHERE priority IS NULL")
        self._conn.commit()

    def _migrate_v54(self) -> None:
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "tags" in cols:
            return
        self._conn.execute(
            "ALTER TABLE facts ADD COLUMN tags TEXT DEFAULT '[]'"
        )
        self._conn.execute("UPDATE facts SET tags = '[]' WHERE tags IS NULL")
        self._conn.commit()

    def _migrate_v55(self) -> None:
        """5.4 → 5.5: 补 archived 列; 老行 archived=0 = visible (行为不变)."""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "archived" in cols:
            return
        self._conn.execute(
            "ALTER TABLE facts ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
        )
        self._conn.execute("UPDATE facts SET archived = 0 WHERE archived IS NULL")
        self._conn.commit()

    def save_fact(
        self,
        category: str,
        content: str,
        source_turn: str = "",
        source_turn_idx: int | None = None,
        priority: int = 0,
        tags: list[str] | None = None,
    ) -> Fact:
        """插入 fact。返回类型 5.0→5.1 由 int 改为 Fact (含 id/ts 等)。"""
        ts = time.time()
        tags_json = self._encode_tags(tags)
        cur = self._conn.execute(
            "INSERT INTO facts "
            "(ts, category, content, source_turn, source_turn_idx, priority, tags, archived) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (ts, category, content, source_turn, source_turn_idx, priority, tags_json),
        )
        self._conn.commit()
        new_id = cur.lastrowid or 0
        return Fact(
            id=new_id, ts=ts, category=category, content=content,
            source_turn=source_turn, source_turn_idx=source_turn_idx,
            priority=priority,
            tags=list(tags) if tags else [],
            archived=False,
        )

    def recall(self, query: str, k: int = 5, category: str | None = None) -> list[Fact]:
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

    def recall_range(
        self,
        start_ts: float | None = None,
        end_ts: float | None = None,
        category: str | None = None,
        k: int = 1000,
    ) -> list[Fact]:
        """按 ts 区间召回。start_ts/end_ts None 表示开放端。"""
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

    def top_frequent(
        self, n: int = 10, category: str | None = None, min_count: int = 2,
    ) -> list[tuple[str, int]]:
        """按 content 出现次数降序，返回 top-N (content, count)。min_count 过滤噪音。"""
        sql = "SELECT content, COUNT(*) AS c FROM facts"
        params: list = []
        if category:
            sql += " WHERE category = ?"; params.append(category)
        sql += " GROUP BY content HAVING c >= ? ORDER BY c DESC, MAX(ts) DESC LIMIT ?"
        params.extend([min_count, n])
        rows = self._conn.execute(sql, params).fetchall()
        return [(r[0], r[1]) for r in rows]

    def recall_by_turn_idx(self, turn_idx: int, k: int = 100) -> list[Fact]:
        """按 turn 整数索引召回。走 idx_facts_source_turn_idx."""
        rows = self._conn.execute(
            f"SELECT {self._FACT_COLS_SQL} FROM facts "
            "WHERE source_turn_idx = ? ORDER BY ts DESC LIMIT ?",
            (turn_idx, k),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def delete_by_turn_idx(self, turn_idx: int) -> int:
        """按 turn 整数索引真删。配合 snapshot 回滚。"""
        cur = self._conn.execute(
            "DELETE FROM facts WHERE source_turn_idx = ?", (turn_idx,)
        )
        self._conn.commit()
        return cur.rowcount

    def recall_high_priority(
        self, k: int = 10, category: str | None = None, min_priority: int = 1,
    ) -> list[Fact]:
        """按 priority DESC, ts DESC 排序召回。走 idx_facts_category_priority_ts."""
        sql = f"SELECT {self._FACT_COLS_SQL} FROM facts WHERE priority >= ?"
        params: list = [min_priority]
        if category:
            sql += " AND category = ?"; params.append(category)
        sql += " ORDER BY priority DESC, ts DESC LIMIT ?"
        params.append(k)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def recall_by_tag(self, tag: str, k: int = 10) -> list[Fact]:
        """按 tag 跨 category 横向召回。LIKE '%"tag"%' 走 idx_facts_tags."""
        if not tag:
            return []
        sql = (
            f"SELECT {self._FACT_COLS_SQL} FROM facts WHERE tags LIKE ? "
            "ORDER BY ts DESC LIMIT ?"
        )
        rows = self._conn.execute(sql, (f'%"{tag}"%', k)).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def recent(self, n: int = 20) -> list[Fact]:
        rows = self._conn.execute(
            f"SELECT {self._FACT_COLS_SQL} FROM facts ORDER BY ts DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    # === 5.5 新方法: 软删除 ===

    def archive_fact(self, fact_id: int) -> bool:
        """软删除: 标 archived=1。已 archived 返回 False (幂等).

        与 delete_by_turn_idx (真删) 互补:
          - 真删 = snapshot 回滚等不可恢复动作
          - 软删 = 暂存/合规/审计场景, 可用 unarchive_fact() 恢复
        不存在的 id 返回 False (rowcount=0).
        """
        cur = self._conn.execute(
            "UPDATE facts SET archived = 1 WHERE id = ? AND archived = 0",
            (fact_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def unarchive_fact(self, fact_id: int) -> bool:
        """软删恢复: archived=1 → 0。已 active 返回 False (幂等)."""
        cur = self._conn.execute(
            "UPDATE facts SET archived = 0 WHERE id = ? AND archived = 1",
            (fact_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def recall_active(
        self, query: str = "", k: int = 10, category: str | None = None,
    ) -> list[Fact]:
        """默认召回 active (archived=0) 行。走 partial idx_facts_active.

        主路径 WHERE archived=0 ORDER BY ts DESC LIMIT k, partial index 让:
          a) archived=0 用 partial 条件做 index seek
          b) ts DESC 索引顺序, ORDER BY 零成本
          c) LIMIT 提前结束
        category 过滤时 partial index 仍可走 (SQLite 自动选最优), 或退化到
        idx_facts_category_ts (archived=0 是行过滤, 但 archived=0 行占比高时仍优).
        """
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
    def count_active(self) -> int:
        """统计 active (archived=0) 行数。走 partial idx_facts_active O(log n)."""
        return self._conn.execute(
            "SELECT COUNT(*) FROM facts WHERE archived = 0"
        ).fetchone()[0]

    def count(self) -> int:
        """统计所有行 (含 archived)。与 count_active() 对偶。"""
        return self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    def close(self) -> None:
        self._conn.close()

    def compress_if_needed(self, messages: list, budget_tokens: int, target_ratio: float = 0.7) -> list:
        from ..compression.simple import SimpleCompression
        return SimpleCompression(budget_tokens=budget_tokens, target_ratio=target_ratio).compress(messages)
