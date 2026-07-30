"""MemoryManager: SQLite 事实存取 + 全文 + 元数据索引。

Schema 版本演进 (按 _migrate_v5X 顺序幂等执行):
    5.0: 初始 (id, ts, category, content, source_turn, priority=0, tags, archived=0, title)
    5.1: +source_turn_idx; +idx_facts_source_turn_idx; +recall_by_turn_idx
    5.2: +delete_by_turn_idx(turn_idx) -> int  (清理单 turn 全部 fact)
    5.3: +Fact.priority; +idx_facts_category_priority_ts; +recall_high_priority
    5.5: +Fact.archived; +idx_facts_active (partial); +archive/unarchive/recall_active
    5.6: +Fact.title; +idx_facts_category_ts  (短标题, 默认空串)
    5.7: +Fact.confidence; +idx_facts_confidence_ts; +update_confidence; +recall_by_min_confidence

新版本字段/方法请同步追加到顶部注释, 并写 _migrate_v5X(no-op on 已有列)。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional


SCHEMA_VERSION = 57  # 5.7


@dataclass
class Fact:
    """一条长期记忆。"""

    id: int
    ts: float
    category: str
    content: str
    source_turn: Optional[str] = None
    source_turn_idx: Optional[int] = None  # 5.1
    priority: int = 0  # 5.3
    tags: list[str] = field(default_factory=list)
    archived: bool = False  # 5.5
    title: str = ""  # 5.6: 短标题, 默认空串
    confidence: float = 1.0  # 5.7: 0.0~1.0, 越高越可靠


class MemoryManager:
    """单进程 SQLite 包装。线程安全 (同一连接 + lock)。

    DB 路径: settings.memory_db 指向 <repo_root>/memory/long_term/facts.db
    """

    _TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS facts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ts              REAL NOT NULL,
        category        TEXT NOT NULL,
        content         TEXT NOT NULL,
        source_turn     TEXT,
        source_turn_idx INTEGER,  -- 5.1
        priority        INTEGER NOT NULL DEFAULT 0,  -- 5.3
        tags            TEXT NOT NULL DEFAULT '[]',  -- JSON list
        -- 5.5
        archived        INTEGER NOT NULL DEFAULT 0,
        -- 5.6
        title           TEXT NOT NULL DEFAULT '',
        -- 5.7
        confidence      REAL NOT NULL DEFAULT 1.0
    );
    """

    _INDEXES_DDL = [
        # 5.1
        "CREATE INDEX IF NOT EXISTS idx_facts_source_turn_idx ON facts(source_turn_idx)",
        # 5.3
        "CREATE INDEX IF NOT EXISTS idx_facts_category_priority_ts "
        "ON facts(category, priority DESC, ts DESC)",
        # 5.5 partial index: 只索引未归档行
        "CREATE INDEX IF NOT EXISTS idx_facts_active ON facts(archived) WHERE archived = 0",
        # 5.6
        "CREATE INDEX IF NOT EXISTS idx_facts_category_ts ON facts(category, ts DESC)",
        # 5.7
        "CREATE INDEX IF NOT EXISTS idx_facts_confidence_ts "
        "ON facts(confidence DESC, ts DESC)",
    ]

    def __init__(self, db_path=None) -> None:
        """打开 SQLite 连接, 初始化 schema 并跑一遍所有 migration。

        DB 来源优先级: 显式 ``db_path`` > ``settings.memory_db`` (通常为
        ``<repo_root>/memory/long_term/facts.db``); 通过
        :func:`xragent.config.settings.get_settings` 解析。

        启用 ``journal_mode=WAL`` + ``foreign_keys=ON``,并把 ``row_factory``
        设成 :class:`sqlite3.Row` 让所有查询返回字典式行。

        Args:
            db_path: 可选路径覆盖; ``None`` 时用 settings.memory_db。

        Side effects:
            打开 :class:`sqlite3.Connection`、执行 ``_init_schema`` 与
            ``_migrate_all``,首次会创建 ``facts`` 表和所有索引。
        """
        from xragent.config.settings import get_settings

        s = get_settings()
        self._db_path = str(db_path or s.memory_db)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self._migrate_all()

    def close(self) -> None:
        """关闭底层 SQLite 连接, 释放 file handle。

        用 ``try/except sqlite3.ProgrammingError`` 吞掉重复关闭的报错,
        让外部 ``with`` 风格或显式 ``close()`` 多次调用都安全。
        """
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.ProgrammingError:
                pass

    # ---- schema ----

    def _init_schema(self) -> None:
        """``CREATE TABLE IF NOT EXISTS`` + 全部索引, 幂等。

        一个事务里先建表后建索引, 避免并发场景下表还没建好就被查询。
        后续 :meth:`_migrate_all` 会按 schema 版本补字段 / 索引。
        """
        with self._lock, self._conn:
            self._conn.executescript(self._TABLE_DDL)
            for ddl in self._INDEXES_DDL:
                self._conn.execute(ddl)

    def _migrate_all(self) -> None:
        """依次执行 _migrate_v5X, 幂等。"""
        self._migrate_v51()
        self._migrate_v53()
        self._migrate_v55()
        self._migrate_v56()
        self._migrate_v57()

    # ---- 5.1 ----
    def _migrate_v51(self) -> None:
        """5.0 -> 5.1: facts +source_turn_idx; +idx_facts_source_turn_idx; +recall_by_turn_idx"""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()}
        if "source_turn_idx" not in cols:
            with self._lock, self._conn:
                self._conn.execute("ALTER TABLE facts ADD COLUMN source_turn_idx INTEGER")
        # 索引幂等 (IF NOT EXISTS)
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_facts_source_turn_idx "
                "ON facts(source_turn_idx)"
            )

    # ---- 5.3 ----
    def _migrate_v53(self) -> None:
        """5.2 -> 5.3: facts +priority (默认 0); +idx_facts_category_priority_ts."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()}
        if "priority" not in cols:
            with self._lock, self._conn:
                self._conn.execute(
                    "ALTER TABLE facts ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
                )
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_facts_category_priority_ts "
                "ON facts(category, priority DESC, ts DESC)"
            )

    # ---- 5.5 ----
    def _migrate_v55(self) -> None:
        """5.4 -> 5.5: facts +archived (默认 0); +idx_facts_active (partial)."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()}
        if "archived" not in cols:
            with self._lock, self._conn:
                self._conn.execute(
                    "ALTER TABLE facts ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
                )
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_facts_active "
                "ON facts(archived) WHERE archived = 0"
            )

    # ---- 5.6 ----
    def _migrate_v56(self) -> None:
        """5.5 -> 5.6: facts +title (默认空串); +idx_facts_category_ts."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()}
        if "title" not in cols:
            with self._lock, self._conn:
                self._conn.execute(
                    "ALTER TABLE facts ADD COLUMN title TEXT NOT NULL DEFAULT ''"
                )
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_facts_category_ts "
                "ON facts(category, ts DESC)"
            )

    # ---- 5.7 ----
    def _migrate_v57(self) -> None:
        """5.6 -> 5.7: facts +confidence (REAL NOT NULL DEFAULT 1.0); +idx_facts_confidence_ts;
        +update_confidence; +recall_by_min_confidence.
        """
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()}
        if "confidence" not in cols:
            with self._lock, self._conn:
                self._conn.execute(
                    "ALTER TABLE facts ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0"
                )
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_facts_confidence_ts "
                "ON facts(confidence DESC, ts DESC)"
            )

    # ---- CRUD ----

    def save_fact(
        self,
        category: str,
        content: str,
        source_turn: Optional[str] = None,
        source_turn_idx: Optional[int] = None,
        tags: Optional[Iterable[str]] = None,
        priority: int = 0,
        title: str = "",
        confidence: float = 1.0,
    ) -> Fact:
        """落库并返回带 id 的 Fact。"""
        import json as _json

        ts = time.time()
        tags_json = _json.dumps(list(tags or []))
        # clamp confidence 到 [0, 1]
        conf = max(0.0, min(1.0, float(confidence)))
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO facts (ts, category, content, source_turn, source_turn_idx, "
                "tags, priority, title, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts,
                    category,
                    content,
                    source_turn,
                    source_turn_idx,
                    tags_json,
                    priority,
                    title,
                    conf,
                ),
            )
            new_id = cur.lastrowid
        return Fact(
            id=new_id,
            ts=ts,
            category=category,
            content=content,
            source_turn=source_turn,
            source_turn_idx=source_turn_idx,
            priority=priority,
            tags=list(tags or []),
            archived=False,
            title=title,
            confidence=conf,
        )

    def _row_to_fact(self, r: sqlite3.Row) -> Fact:
        """把 :class:`sqlite3.Row` 转成 :class:`Fact` dataclass。

        ``tags`` 字段在 DB 里是 JSON 字符串, 这里 ``json.loads`` 反序列化;
        解析失败时回退空列表, 避免因单行坏数据让整条 recall 链抛错。

        Args:
            r: ``SELECT * FROM facts`` 返回的单行, 必须含 :class:`Fact` 全字段。

        Returns:
            Fact: 行内容映射出的 Fact; ``archived`` 转 ``bool``, ``tags`` 转 ``list[str]``。
        """
        import json as _json

        try:
            tags = _json.loads(r["tags"] or "[]")
        except _json.JSONDecodeError:
            tags = []
        return Fact(
            id=r["id"],
            ts=r["ts"],
            category=r["category"],
            content=r["content"],
            source_turn=r["source_turn"],
            source_turn_idx=r["source_turn_idx"],
            priority=r["priority"],
            tags=tags,
            archived=bool(r["archived"]),
            title=r["title"],
            confidence=float(r["confidence"]),
        )

    def recall(
        self,
        query: str = "",
        k: int = 5,
        category: Optional[str] = None,
    ) -> list[Fact]:
        """全文 LIKE 召回 (兼容老路径, 不过滤 archived)."""
        sql = "SELECT * FROM facts WHERE 1=1"
        params: list = []
        if query:
            sql += " AND content LIKE ?"
            params.append(f"%{query}%")
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(k)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def recall_range(
        self,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        category: Optional[str] = None,
        k: int = 1000,
    ) -> list[Fact]:
        """按时间窗口召回; 开放端用 None."""
        sql = "SELECT * FROM facts WHERE 1=1"
        params: list = []
        if start_ts is not None:
            sql += " AND ts >= ?"
            params.append(start_ts)
        if end_ts is not None:
            sql += " AND ts <= ?"
            params.append(end_ts)
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(k)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def top_frequent(
        self,
        n: int = 10,
        category: Optional[str] = None,
        min_count: int = 2,
    ) -> list[tuple[str, int]]:
        """按 content 频次降序的 top-N. 过滤 archived=0."""
        sql = (
            "SELECT content, COUNT(*) AS c FROM facts "
            "WHERE archived = 0"
        )
        params: list = []
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " GROUP BY content HAVING c >= ? ORDER BY c DESC, MAX(ts) DESC LIMIT ?"
        params.extend([min_count, n])
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [(r["content"], r["c"]) for r in rows]

    def recent(self, n: int = 10) -> list[Fact]:
        """最近的 n 条 (含 archived)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM facts ORDER BY ts DESC LIMIT ?", (n,)
            ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def count(self) -> int:
        """返回 ``facts`` 表总行数 (含 archived)。

        用于 /diag 类自检命令和 pytest fixture; 不区分 archived, 想看
        活跃数量请改用 :meth:`count_active`。

        Returns:
            int: ``SELECT COUNT(*) FROM facts`` 的结果。
        """
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) AS c FROM facts").fetchone()["c"]

    def recall_by_turn_idx(self, turn_idx: int) -> list[Fact]:
        """5.1 新方法: 走 idx_facts_source_turn_idx."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM facts WHERE source_turn_idx = ? ORDER BY ts ASC",
                (turn_idx,),
            ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def delete_by_turn_idx(self, turn_idx: int) -> int:
        """5.2 新方法: 删除该 turn 的全部 fact, 返回删除条数。NULL idx 不动。"""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM facts WHERE source_turn_idx = ?", (turn_idx,)
            )
            return cur.rowcount

    def recall_high_priority(
        self,
        k: int = 5,
        category: Optional[str] = None,
        min_priority: int = 1,
    ) -> list[Fact]:
        """5.3 新方法: 按 priority DESC, ts DESC 召回 (archived=0)."""
        sql = "SELECT * FROM facts WHERE priority >= ? AND archived = 0"
        params: list = [min_priority]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY priority DESC, ts DESC LIMIT ?"
        params.append(k)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    # ---- 5.5 ----

    def archive_fact(self, fact_id: int) -> bool:
        """5.5: 标 archived=1; 已归档则返回 False. 不存在 id 返回 False."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE facts SET archived = 1 WHERE id = ? AND archived = 0",
                (fact_id,),
            )
            return cur.rowcount > 0

    def unarchive_fact(self, fact_id: int) -> bool:
        """5.5: archived=1 恢复为 0; 已活跃返回 False."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE facts SET archived = 0 WHERE id = ? AND archived = 1",
                (fact_id,),
            )
            return cur.rowcount > 0

    def recall_active(
        self,
        query: str = "",
        k: int = 5,
        category: Optional[str] = None,
    ) -> list[Fact]:
        """5.5: 默认排除 archived=1, 走 idx_facts_active partial index."""
        sql = "SELECT * FROM facts WHERE archived = 0"
        params: list = []
        if query:
            sql += " AND content LIKE ?"
            params.append(f"%{query}%")
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(k)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def count_active(self) -> int:
        """5.5: 只算 archived=0 行。"""
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) AS c FROM facts WHERE archived = 0"
            ).fetchone()["c"]

    # ---- 5.7 ----

    def update_confidence(self, fact_id: int, confidence: float) -> Optional[Fact]:
        """5.7: 更新 confidence (clamp 到 [0, 1]). 不存在 id 返回 None。"""
        conf = max(0.0, min(1.0, float(confidence)))
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE facts SET confidence = ? WHERE id = ?",
                (conf, fact_id),
            )
            if cur.rowcount == 0:
                return None
        # 读回最新行
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM facts WHERE id = ?", (fact_id,)
            ).fetchone()
        return self._row_to_fact(row) if row else None

    def recall_by_min_confidence(
        self,
        min_confidence: float = 0.5,
        k: int = 5,
        category: Optional[str] = None,
        include_archived: bool = False,
    ) -> list[Fact]:
        """5.7 新方法: 按 confidence DESC, ts DESC 召回 (走 idx_facts_confidence_ts).
        默认排除 archived 行; include_archived=True 时不过滤。
        """
        sql = "SELECT * FROM facts WHERE confidence >= ?"
        params: list = [min_confidence]
        if not include_archived:
            sql += " AND archived = 0"
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY confidence DESC, ts DESC LIMIT ?"
        params.append(k)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]
