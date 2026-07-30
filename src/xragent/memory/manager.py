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
    # 5.1: 新增字段，对应 DB 列 source_turn_idx (INTEGER, nullable)。
    # 与 source_turn (TEXT, turn id 字符串) 并存: 字符串给人看, 整数给索引。
    # 新字段放在末尾 + 默认 None, 老代码 positional 构造 5 个字段不会破坏。
    source_turn_idx: int | None = None


class MemoryManager:
    # === Schema 版本: 5.0 → 5.1 ===
    # 变更:
    #   1. facts 表新增列  source_turn_idx INTEGER  (nullable)
    #   2. 新增索引       idx_facts_source_turn_idx ON facts(source_turn_idx)
    # 用途:
    #   - 让"按 turn 索引召回 fact"成为一等公民 (recall_by_turn_idx)
    #   - 配合审计/回滚场景 ("这一轮 AI 存了哪些 fact?")
    # 向后兼容:
    #   - 新字段 nullable; 老行 source_turn_idx=NULL, recall_by_turn_idx 会跳过
    #   - 新 DB 走 BASE_SCHEMA 直接含新列; 老 DB 走 _migrate_v51 幂等 ALTER
    #   - 旧 API 调用方不受影响: source_turn (TEXT) 仍然保留
    BASE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS facts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts REAL NOT NULL,
      category TEXT NOT NULL,
      content TEXT NOT NULL,
      source_turn TEXT,
      source_turn_idx INTEGER
    );
    """

    INDEX_SCHEMA = """
    CREATE INDEX IF NOT EXISTS idx_facts_category_ts ON facts(category, ts DESC);
    CREATE INDEX IF NOT EXISTS idx_facts_ts ON facts(ts DESC);
    CREATE INDEX IF NOT EXISTS idx_facts_source_turn ON facts(source_turn);
    CREATE INDEX IF NOT EXISTS idx_facts_source_turn_idx ON facts(source_turn_idx);
    """

    # 兼容旧引用 (任何外部代码读 SCHEMA 仍可拿到完整脚本)
    SCHEMA = BASE_SCHEMA + INDEX_SCHEMA

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
    # 4. (source_turn_idx) index: 新增, 与 #3 对偶, 走整数 turn 索引。
    # 5. Old single-column idx_facts_category is a prefix of the composite and is
    #    therefore redundant; existing DBs may still carry it (harmless).

    # SELECT 投影顺序约定：所有 SELECT 都要按这个 tuple 顺序输出, _row_to_fact 才能
    # 用 fixed indices 还原 Fact。新加列必须追加在末尾 + 同步更新本约定。
    _FACT_COLUMNS = ("id", "ts", "category", "content", "source_turn", "source_turn_idx")

    @staticmethod
    def _row_to_fact(row: tuple) -> Fact:
        """DB 行 → Fact 还原。``_FACT_COLUMNS`` 是投影顺序契约, 改 SELECT 时同步改。

        抽到此处前 4 个召回方法 (recall/recall_range/recall_by_turn_idx/recent) 各写
        一份 7 行 ``Fact(id=r[0], ts=r[1], ...)``, 加列时容易漏一处; 集中后只改一处。
        """
        return Fact(
            id=row[0],
            ts=row[1],
            category=row[2],
            content=row[3],
            source_turn=row[4],
            source_turn_idx=row[5],
        )

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
        # 顺序: BASE_SCHEMA (新 DB 拿全列) -> 幂等 migration (老 DB 补列) -> 索引
        self._conn.executescript(self.BASE_SCHEMA)
        self._migrate_v51()
        self._conn.executescript(self.INDEX_SCHEMA)
        self._conn.commit()

    def _migrate_v51(self) -> None:
        """5.0 → 5.1: 为已存在的 facts 表补 source_turn_idx 列。

        SQLite 没有 ADD COLUMN IF NOT EXISTS, 必须先 PRAGMA table_info 探列。
        新 DB (走 BASE_SCHEMA) 已经有列, 这里会跳过; 老 DB (走 5.0 schema) 才
        真正执行 ALTER。幂等。
        """
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "source_turn_idx" not in cols:
            self._conn.execute("ALTER TABLE facts ADD COLUMN source_turn_idx INTEGER")
            self._conn.commit()

    def save_fact(
        self,
        category: str,
        content: str,
        source_turn: str = "",
        source_turn_idx: int | None = None,
    ) -> Fact:
        """插入一条 fact, 返回刚插入的 Fact 对象 (含 db 自增 id 与 ts)。

        返回类型 5.0→5.1 由 int 改为 Fact:
          - 老调用方关心 id: 改用 .id
          - 顺便拿到 ts / category / content, 不必再 recall 一次
        """
        ts = time.time()
        cur = self._conn.execute(
            "INSERT INTO facts (ts, category, content, source_turn, source_turn_idx) "
            "VALUES (?, ?, ?, ?, ?)",
            (ts, category, content, source_turn, source_turn_idx),
        )
        self._conn.commit()
        new_id = cur.lastrowid or 0
        return Fact(
            id=new_id,
            ts=ts,
            category=category,
            content=content,
            source_turn=source_turn,
            source_turn_idx=source_turn_idx,
        )

    def recall(self, query: str, k: int = 5, category: str | None = None) -> list[Fact]:
        sql = "SELECT id, ts, category, content, source_turn, source_turn_idx FROM facts"
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
        return [self._row_to_fact(r) for r in rows]

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
        sql = "SELECT id, ts, category, content, source_turn, source_turn_idx FROM facts"
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
        return [self._row_to_fact(r) for r in rows]

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

    def recall_by_turn_idx(self, turn_idx: int, k: int = 100) -> list[Fact]:
        """按 turn 整数索引召回 fact。5.1 新方法。

        与 source_turn (TEXT, 字符串 id) 的区别: 这里是 INTEGER, 配合
        idx_facts_source_turn_idx 做 O(log n) 查找, 适合"第 N 轮 AI 存了什么"
        这类审计/回滚场景。

        NULL 的 source_turn_idx 会被过滤 (老行 / 没填的写入)。
        """
        rows = self._conn.execute(
            "SELECT id, ts, category, content, source_turn, source_turn_idx "
            "FROM facts WHERE source_turn_idx = ? "
            "ORDER BY ts DESC LIMIT ?",
            (turn_idx, k),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def recent(self, n: int = 20) -> list[Fact]:
        rows = self._conn.execute(
            "SELECT id, ts, category, content, source_turn, source_turn_idx "
            "FROM facts ORDER BY ts DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    def close(self) -> None:
        self._conn.close()

    def compress_if_needed(self, messages: list, budget_tokens: int, target_ratio: float = 0.7) -> list:
        from ..compression.simple import SimpleCompression
        return SimpleCompression(budget_tokens=budget_tokens, target_ratio=target_ratio).compress(messages)