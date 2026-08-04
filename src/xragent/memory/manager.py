"""MemoryManager: SQLite 事实存取 + 全文 + 元数据索引。

Schema 版本演进 (按 _migrate_v5X 顺序幂等执行):
    5.0: 初始 (id, ts, category, content, source_turn, priority=0, tags, archived=0, title)
    5.1: +source_turn_idx; +idx_facts_source_turn_idx; +recall_by_turn_idx
    5.2: +delete_by_turn_idx(turn_idx) -> int  (清理单 turn 全部 fact)
    5.3: +Fact.priority; +idx_facts_category_priority_ts; +recall_high_priority
    5.5: +Fact.archived; +idx_facts_active (partial); +archive/unarchive/recall_active
    5.6: +Fact.title; +idx_facts_category_ts  (短标题, 默认空串)
    5.7: +Fact.confidence; +idx_facts_confidence_ts; +update_confidence; +recall_by_min_confidence
    5.8: +Fact.last_accessed_ts; +idx_facts_last_accessed_ts; +touch_fact; +recall_lru
        (LRU 追踪: save_fact 时初始化=ts, touch_fact 时刷新为当前时间,
        recall_lru 按 last_accessed_ts ASC 召回最久未访问的事实)
    5.9: +idx_facts_tags; +idx_facts_title  (修复 5.7 重构期间因 -456 行删改而
        遗失的索引, 详见 _migrate_v59 docstring)
    5.10: +Fact.expires_ts; +idx_facts_expires_ts (partial);
        +set_expiry(fact_id, ttl_seconds); +recall_unexpired; +purge_expired;
        +Fact.access_count; +idx_facts_access_count_ts;
        +recall_most_accessed / recall_least_accessed / increment_access_count (5.11)
        (TTL 语义: expires_ts 为 unix 时间戳, NULL 表示永不过期;
        partial index 只索引 expires_ts IS NOT NULL 的行, 避免大量永不过期
        的 fact 进入索引拖慢写入; purge_expired / recall_unexpired 都按
        expires_ts < now() / expires_ts >= now() 过滤)

新版本字段/方法请同步追加到顶部注释, 并写 _migrate_v5X(no-op on 已有列)。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable


SCHEMA_VERSION = 511  # 5.11


@dataclass
class Fact:
    """一条长期记忆。"""

    id: int
    ts: float
    category: str
    content: str
    source_turn: str | None = None
    source_turn_idx: int | None = None  # 5.1
    priority: int = 0  # 5.3
    tags: list[str] = field(default_factory=list)
    archived: bool = False  # 5.5
    title: str = ""  # 5.6: 短标题, 默认空串
    confidence: float = 1.0  # 5.7: 0.0~1.0, 越高越可靠
    last_accessed_ts: float = 0.0  # 5.8: LRU 追踪, 默认 0.0; save_fact 时初始化=ts
    expires_ts: float | None = None  # 5.10: TTL 过期 unix 时间戳; None = 永不过期
    access_count: int = 0  # 5.11: 访问次数, 与 last_accessed_ts 配合做精确 LFU


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
        confidence      REAL NOT NULL DEFAULT 1.0,
        -- 5.8: LRU 追踪 (0.0 = 未访问过老行)
        last_accessed_ts REAL NOT NULL DEFAULT 0.0,
        -- 5.10: TTL (NULL = 永不过期, 真实值 = unix 时间戳)
        expires_ts      REAL,
        -- 5.11: 访问计数 (LFU 精确化: 新行=0, 每次 recall/touch 累加)
        access_count    INTEGER NOT NULL DEFAULT 0
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
        # 5.8: LRU 召回最久未访问; ASC 让 ORDER BY last_accessed_ts ASC 直接走索引
        "CREATE INDEX IF NOT EXISTS idx_facts_last_accessed_ts "
        "ON facts(last_accessed_ts ASC)",
        # 5.10: TTL partial index — 只索引 expires_ts IS NOT NULL 的行,
        # 大量永不过期 fact 不会进索引拖慢写入; purge_expired / recall_unexpired
        # 都直接走 ORDER BY expires_ts ASC
        "CREATE INDEX IF NOT EXISTS idx_facts_expires_ts "
        "ON facts(expires_ts ASC) WHERE expires_ts IS NOT NULL",
        # 5.11: LFU 召回最常访问 (DESC 让 ORDER BY access_count DESC 走索引)
        "CREATE INDEX IF NOT EXISTS idx_facts_access_count_ts "
        "ON facts(access_count DESC, ts DESC)",
    ]

    @staticmethod
    def _safe_create_index(conn: sqlite3.Connection, ddl: str) -> bool:
        """幂等执行 ``CREATE INDEX IF NOT EXISTS`` 并吞掉"列/表未就绪"异常。

        Migration 阶段调用此 helper 而不是裸 ``conn.execute(ddl)``, 因为:
          * 老库 schema 版本不齐, 索引可能引用尚未 ``ALTER TABLE`` 加上的列
            (``no such column: ...``);
          * ``_migrate_v59`` 等"补索引"步骤在某些老库上表本身可能缺失
            (``no such table: ...``)。
        这两类异常视为"幂等跳过", 返回 ``False``; 其它异常 (如 SQL 语法错)
        继续往上抛, 让调用方立刻感知。

        Args:
            conn: 已打开的 SQLite 连接; 本方法不消费结果集, ``row_factory``
                不影响行为。
            ddl: 单条 ``CREATE INDEX IF NOT EXISTS ...`` SQL 语句, 必须为
                ``str``; 非 str 会原样下传, 由 SQLite 层抛错。

        Returns:
            bool: 索引成功创建或已存在 → ``True``; 列/表缺失导致失败 → ``False``
            (幂等跳过)。

        Raises:
            sqlite3.Error: 上述两类"已知可跳过"以外的异常 (如语法错误、权限
                问题、磁盘满); 透传给调用方, 不在本 helper 静默吞掉。
        """
        try:
            conn.execute(ddl)
            return True
        except Exception as e:
            if "no such column" in str(e) or "no such table" in str(e):
                return False
            raise

    def __init__(self, db_path: str | None = None) -> None:
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

    def recall_by_tag(self, tag: str, k: int = 10) -> list[Fact]:
        """5.4 新方法: 按 tag 跨 category 横向召回 fact (newest first)。

        查询模式: WHERE tags LIKE '%"tag"%'
          - JSON 数组里每个元素都有引号包裹, 精确匹配 "python" 不会误匹配
            "pythonic" 或 "cpython"。
          - 走 idx_facts_tags 索引 (B-tree on TEXT, LIKE 后缀为常量时 SQLite
            走索引优化路径)。
          - 顺序按 ts DESC, LIMIT 提前结束。

        Args:
            tag: 单个 tag, 不含引号 (内部加引号)。
            k: 返回条数上限, 默认 10。

        Returns:
            按 ts DESC 排序的 Fact 列表。空 tag 返回 ``[]`` (避免 LIKE '%%' 全表扫)。
        """
        if not tag:
            return []
        sql = (
            "SELECT * FROM facts WHERE tags LIKE ? "
            "ORDER BY ts DESC LIMIT ?"
        )
        rows = self._conn.execute(sql, (f'%"{tag}"%', k)).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def recent(self, n: int = 20) -> list[Fact]:
        """最新 N 条 fact (含已归档), 按 ts DESC。

        与 ``recall_active(n)`` 区别: 本方法不过滤 archived, 用于调试 /
        复盘类场景; UI / LLM-facing wrapper 通常用 ``recall_active``。

        Args:
            n: 返回条数上限, 默认 20。

        Returns:
            按 ts DESC 排序的 Fact 列表 (最多 n 条)。
        """
        sql = "SELECT * FROM facts ORDER BY ts DESC LIMIT ?"
        rows = self._conn.execute(sql, (n,)).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def recall_by_title(self, title: str, k: int = 10) -> list[Fact]:
        """5.6 新方法: 按 title 精确匹配召回 (走 idx_facts_title)。

        与 :meth:`recall_by_tag` 互补 —— tag 走模糊 LIKE, title 走 ``=`` 精确。
        title 稀疏 (大量 row title=''), NULL / 空 string 都不入 B-tree 索引。

        Args:
            title: 精确等值的 title 字符串。
            k: 返回条数上限, 默认 10。

        Returns:
            按 ts DESC 排序的 Fact 列表。空 title 返回 ``[]``。
        """
        if not title:
            return []
        sql = (
            "SELECT * FROM facts WHERE title = ? "
            "ORDER BY ts DESC LIMIT ?"
        )
        rows = self._conn.execute(sql, (title, k)).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def update_title(self, fact_id: int, new_title: str | None = None) -> Fact | None:
        """5.6 新方法: 更新 title 并返回更新后的 Fact, ``None`` = id 不存在。

        返回类型 ``Fact | None`` 区分两种失败:
          * rowcount=0 → ``None`` (id 不存在)
          * 写后再 SELECT 取不到 row → ``None`` (防御, 实际不应发生)

        Args:
            fact_id: 主键 id。
            new_title: 新 title; ``None`` 表示"清空" (列置 ``""``, 因为
                title 列是 ``NOT NULL DEFAULT ''``; wrapper 把"清空"语义
                在 LLM-facing 层表达成 ``None``, DB 层收口为 ``""``)。

        Returns:
            更新后的 :class:`Fact`; id 不存在时 ``None``。
        """
        title_eff = "" if new_title is None else new_title
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE facts SET title = ? WHERE id = ?",
                (title_eff, fact_id),
            )
            if cur.rowcount == 0:
                return None
            row = self._conn.execute(
                "SELECT * FROM facts WHERE id = ?", (fact_id,)
            ).fetchone()
        return self._row_to_fact(row) if row else None

    def compress_if_needed(
        self,
        messages: list,
        budget_tokens: int,
        target_ratio: float = 0.7,
    ) -> list:
        """判断消息列表是否需要压缩, 超出预算时丢最早的非 system 消息.

        走 :class:`xragent.compression.simple.SimpleCompression`, 与
        ``scripts/test`` 的现有测试契约一致. ``budget_tokens`` 来自
        ``settings.context_budget_tokens`` (默认 20_000); ``target_ratio``
        默认 0.7 (留 30% 给后续迭代).

        Args:
            messages: 待压缩消息序列 (任何含 ``.role`` / ``.content`` 字段的对象).
            budget_tokens: 触发压缩的 token 上限.
            target_ratio: 目标压缩后占 budget 的比例.

        Returns:
            list: 压缩后的新列表. 未超预算时返回入参本身 (同一对象).
        """
        from ..compression.simple import SimpleCompression
        c = SimpleCompression(budget_tokens=budget_tokens, target_ratio=target_ratio)
        if not c.should_compress(messages):
            return messages
        return c.compress(messages)

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
                try:
                    self._conn.execute(ddl)
                except Exception as e:
                    if "no such column" not in str(e):
                        raise

    def _migrate_all(self) -> None:
        """依次执行 _migrate_v5X, 幂等。"""
        self._migrate_v51()
        self._migrate_v53()
        self._migrate_v54()  # 5.4: idx_facts_tags
        self._migrate_v55()
        self._migrate_v56()  # 5.6: idx_facts_title
        self._migrate_v57()
        self._migrate_v58()
        self._migrate_v59()  # 5.9: 恢复 5.4/5.6 时代丢失的索引
        self._migrate_v510()  # 5.10: +expires_ts + TTL 索引 + 3 方法
        self._migrate_v511()  # 5.11: +access_count + LFU 索引 + 3 recall 方法

    # ---- 5.1 ----
    def _migrate_v51(self) -> None:
        """5.0 -> 5.1: facts +source_turn_idx; +idx_facts_source_turn_idx; +recall_by_turn_idx"""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()}
        if "source_turn_idx" not in cols:
            with self._lock, self._conn:
                self._conn.execute("ALTER TABLE facts ADD COLUMN source_turn_idx INTEGER")
        # 索引幂等 (IF NOT EXISTS)
        with self._lock, self._conn:
                            self._safe_create_index(
                self._conn,
                "CREATE INDEX IF NOT EXISTS idx_facts_source_turn_idx  ON facts(source_turn_idx)",
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
                            self._safe_create_index(
                self._conn,
                "CREATE INDEX IF NOT EXISTS idx_facts_category_priority_ts  ON facts(category, priority DESC, ts DESC)",
            )

    # ---- 5.4 ----
    def _migrate_v54(self) -> None:
        """5.3 -> 5.4: +idx_facts_tags (B-tree on tags JSON 字段, 配合 LIKE '"tag"' 后缀优化).

        表结构没变, 只加索引. 老库已存在则 CREATE INDEX IF NOT EXISTS 跳过.
        5.7 重构 (-456 行) 时忘了重建, _migrate_v59 也会兜底再补一次."""
        self._safe_create_index(self._conn, "CREATE INDEX IF NOT EXISTS idx_facts_tags ON facts(tags)")

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
                            self._safe_create_index(
                self._conn,
                "CREATE INDEX IF NOT EXISTS idx_facts_category_ts  ON facts(category, ts DESC)",
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
                            self._safe_create_index(
                self._conn,
                "CREATE INDEX IF NOT EXISTS idx_facts_confidence_ts  ON facts(confidence DESC, ts DESC)",
            )

    # ---- 5.8 ----
    def _migrate_v58(self) -> None:
        """5.7 -> 5.8: facts +last_accessed_ts (REAL NOT NULL DEFAULT 0.0, LRU 追踪);
        +idx_facts_last_accessed_ts; +touch_fact; +recall_lru.

        老行 last_accessed_ts=0.0 (DEFAULT), 既表示"从未被 touch 过",也保证
        recall_lru 把老行排在最前 (适合冷数据淘汰 / 内存压力时的低优先级回收)。
        """
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()}
        if "last_accessed_ts" not in cols:
            with self._lock, self._conn:
                self._conn.execute(
                    "ALTER TABLE facts ADD COLUMN last_accessed_ts "
                    "REAL NOT NULL DEFAULT 0.0"
                )
        with self._lock, self._conn:
                            self._safe_create_index(
                self._conn,
                "CREATE INDEX IF NOT EXISTS idx_facts_last_accessed_ts  ON facts(last_accessed_ts ASC)",
            )

    def _migrate_v59(self) -> None:
        """5.8 -> 5.9: 恢复 5.4/5.6 时代丢失的 idx_facts_tags / idx_facts_title 两个索引。

        仅 DDL, 不动 data; 老库已存在则 CREATE INDEX IF NOT EXISTS 直接跳过。
        之前 query 走全表扫描也能跑 (数据量小), 但跨 turn 的 cumulative fact 量起来
        后 LIKE '"tag"' 性能塌方。这里补索引只让路径变窄, 不修改任何 row。

        现状对账:
          * idx_facts_tags  (5.4) — 5.7 大重构 (-456 行) 时随 method recall_by_tag
            一并遗失。
          * idx_facts_title (5.6) — 5.7 重构时随 method recall_by_title / update_title
            一并遗失。

        修复策略: 幂等 CREATE INDEX IF NOT EXISTS, 跑完一遍后下次启动 _migrate_all
        会自动 skip (PRAGMA user_version 已经 +1)。
        """
        with self._lock, self._conn:
            self._safe_create_index(self._conn, "CREATE INDEX IF NOT EXISTS idx_facts_tags ON facts(tags)")
            self._safe_create_index(self._conn, "CREATE INDEX IF NOT EXISTS idx_facts_title ON facts(title)")

    # ---- 5.10 ----
    def _migrate_v510(self) -> None:
        """5.9 -> 5.10: facts +expires_ts (REAL NULL); +idx_facts_expires_ts (partial).

        新列 expires_ts 默认 NULL — 等价于"永不过期", 对历史存量行零侵入。
        partial index 仅覆盖 expires_ts IS NOT NULL 的行, 避免"绝大多数 fact
        永不过期"场景下索引体积过大; purge_expired / recall_unexpired 都走
        WHERE expires_ts < now() 或 WHERE expires_ts >= now() 配合 ORDER BY
        expires_ts ASC, partial index 会自动启用 (SQLite 优化器识别 WHERE
        谓词与 partial index 谓词匹配时直接走索引)。

        三方法在类尾部添加, 此处仅做 DDL。
        """
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()}
        if "expires_ts" not in cols:
            with self._lock, self._conn:
                self._conn.execute("ALTER TABLE facts ADD COLUMN expires_ts REAL")
        with self._lock, self._conn:
            self._safe_create_index(
                self._conn,
                "CREATE INDEX IF NOT EXISTS idx_facts_expires_ts "
                "ON facts(expires_ts ASC) WHERE expires_ts IS NOT NULL",
            )

    # ---- 5.11 ----
    def _migrate_v511(self) -> None:
        """5.10 -> 5.11: facts +access_count (INTEGER DEFAULT 0);
+idx_facts_access_count_ts.

        access_count 默认 0 — 对历史存量行零侵入 (新写入不再 +1);
        recall_most_accessed / recall_least_accessed 通过
        WHERE access_count >= 0 自动覆盖存量行。
        复合索引 (access_count DESC, ts DESC) 让 ORDER BY 直接走索引,
        配合 WHERE 过滤 archived=0 时可与 idx_facts_active 共存
        (SQLite 优化器按 cost 选 plan)。

        三个方法 (recall_most_accessed / recall_least_accessed /
        increment_access_count) 在类尾部添加, 此处仅做 DDL。
        """
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()}
        if "access_count" not in cols:
            with self._lock, self._conn:
                self._conn.execute(
                    "ALTER TABLE facts ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0"
                )
        with self._lock, self._conn:
            self._safe_create_index(
                self._conn,
                "CREATE INDEX IF NOT EXISTS idx_facts_access_count_ts "
                "ON facts(access_count DESC, ts DESC)",
            )

    # ---- CRUD ----

    def save_fact(
        self,
        category: str,
        content: str,
        source_turn: str | None = None,
        source_turn_idx: int | None = None,
        tags: Iterable[str] | None = None,
        priority: int = 0,
        title: str = "",
        confidence: float = 1.0,
        expires_ts: float | None = None,  # 5.10: TTL 过期时间 (unix)
        access_count: int = 0,  # 5.11: 初始访问计数 (默认 0)
    ) -> Fact:
        """落库并返回带 id 的 Fact。"""
        import json as _json

        ts = time.time()
        tags_json = _json.dumps(list(tags or []), ensure_ascii=False)
        # title 列 NOT NULL DEFAULT '', 输入 None 时收敛成空串
        # (老 schema 已经是 NOT NULL, 不在 save_fact 抛 IntegrityError)
        title_eff = title if title is not None else ""
        # clamp confidence 到 [0, 1]
        conf = max(0.0, min(1.0, float(confidence)))
        # 5.8: 新行 last_accessed_ts 初始化为 ts (创建即"访问"),避免新建行被
        # recall_lru 误判为冷数据
        last_access = ts
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO facts (ts, category, content, source_turn, source_turn_idx, "
                "tags, priority, title, confidence, last_accessed_ts, expires_ts, "
                "access_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts,
                    category,
                    content,
                    source_turn,
                    source_turn_idx,
                    tags_json,
                    priority,
                    title_eff,
                    conf,
                    last_access,
                    expires_ts,
                    access_count,
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
            title=title_eff,
            confidence=conf,
            last_accessed_ts=last_access,
            expires_ts=expires_ts,
            access_count=access_count,
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
            last_accessed_ts=float(r["last_accessed_ts"]),
            expires_ts=r["expires_ts"],
            access_count=int(r["access_count"]),
        )

    def recall(
        self,
        query: str = "",
        k: int = 5,
        category: str | None = None,
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
        start_ts: float | None = None,
        end_ts: float | None = None,
        category: str | None = None,
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
        category: str | None = None,
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

    def count(self) -> int:
        """总 fact 数 (含 archived)."""
        with self._lock:
            r = self._conn.execute("SELECT COUNT(*) AS c FROM facts").fetchone()
        return int(r["c"])

    def recall_by_turn_idx(self, turn_idx: int, k: int = 1000) -> list[Fact]:
        """5.1: 按 turn_idx 召回去重 (idx_facts_source_turn_idx)."""
        sql = (
            "SELECT * FROM facts WHERE source_turn_idx = ? "
            "ORDER BY ts DESC LIMIT ?"
        )
        with self._lock:
            rows = self._conn.execute(sql, (turn_idx, k)).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def delete_by_turn_idx(self, turn_idx: int) -> int:
        """5.2: 删除指定 turn_idx 的所有 fact (cleanup hook); 返回影响行数."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM facts WHERE source_turn_idx = ?", (turn_idx,)
            )
            return cur.rowcount

    def recall_high_priority(
        self,
        min_priority: int = 1,
        category: str | None = None,
        k: int = 50,
    ) -> list[Fact]:
        """5.3: 高优先级召回 (idx_facts_category_priority_ts)."""
        sql = "SELECT * FROM facts WHERE priority >= ?"
        params: list = [min_priority]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY priority DESC, ts DESC LIMIT ?"
        params.append(k)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def archive_fact(self, fact_id: int) -> bool:
        """5.5: 软删除 — 标 archived=1; 已 archived 返回 False (幂等).

        与 :meth:`unarchive_fact` 对称: 用 status filter 避免"重置同样值"
        算 rowcount=1 而非 idempotent。
        """
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE facts SET archived = 1 WHERE id = ? AND archived = 0",
                (fact_id,),
            )
            return cur.rowcount > 0

    def unarchive_fact(self, fact_id: int) -> bool:
        """5.5: 取消归档 (archived=0); 幂等 — 已 archived=0 时返回 False.

        与 :meth:`archive_fact` 对称: 都加 status filter, 避免"重置同样值"
        仍算 rowcount=1 而非 idempotent。
        """
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
        category: str | None = None,
    ) -> list[Fact]:
        """5.5: 仅召回未归档 (partial idx_facts_active)."""
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
        """5.5: 未归档 fact 数 (走 idx_facts_active)."""
        with self._lock:
            r = self._conn.execute(
                "SELECT COUNT(*) AS c FROM facts WHERE archived = 0"
            ).fetchone()
        return int(r["c"])

    def update_confidence(self, fact_id: int, confidence: float) -> Fact | None:
        """5.7: 更新某条 fact 的 confidence (clamp 到 [0,1]), 返回更新后 Fact.

        与 5.6 update_title 返回类型对齐 —— 都是"UPDATE + SELECT 回读完整 Fact"。
        调用方拿到的快照避免二次 recall 开销。

        Args:
            fact_id: 主键 id。
            confidence: 0.0~1.0 之间的浮点; 越界自动 clamp。

        Returns:
            更新后的 :class:`Fact`; id 不存在时 ``None``。
        """
        conf = max(0.0, min(1.0, float(confidence)))
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE facts SET confidence = ? WHERE id = ?",
                (conf, fact_id),
            )
            if cur.rowcount == 0:
                return None
            row = self._conn.execute(
                "SELECT * FROM facts WHERE id = ?", (fact_id,)
            ).fetchone()
        return self._row_to_fact(row) if row else None

    def recall_by_min_confidence(
        self,
        min_confidence: float = 0.5,
        category: str | None = None,
        k: int = 100,
        include_archived: bool = False,
    ) -> list[Fact]:
        """5.7: 按最低 confidence 阈值召回 (idx_facts_confidence_ts).

        Args:
            min_confidence: 下限阈值 (含); 默认 0.5。
            category: 按分类过滤; ``None`` 表示跨类。
            k: 返回条数上限, 默认 100。
            include_archived: True 含已归档行 (运维 / debug 用);
                默认 False (LLM-facing recall 与 recall_active 行为对齐)。

        Returns:
            按 confidence DESC, ts DESC 排序的 Fact 列表。
        """
        sql = "SELECT * FROM facts WHERE confidence >= ?"
        params: list = [float(min_confidence)]
        if category:
            sql += " AND category = ?"
            params.append(category)
        if not include_archived:
            sql += " AND archived = 0"
        sql += " ORDER BY confidence DESC, ts DESC LIMIT ?"
        params.append(k)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def touch_fact(self, fact_id: int) -> bool:
        """5.8: 刷新 last_accessed_ts 为当前时间 (LRU 标记"刚被访问").

        调用方在每次把 fact 喂给 LLM / 召回时, 都应该 touch 一下, 让 recall_lru
        能正确反映真实热度. 归档行也允许 touch (不强制只动 active 行).

        Returns:
            bool: 行存在且被更新则 True, fact_id 不存在则 False.
        """
        ts = time.time()
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE facts SET last_accessed_ts = ? WHERE id = ?",
                (ts, fact_id),
            )
            return cur.rowcount > 0

    def recall_lru(
        self,
        k: int = 10,
        active_only: bool = True,
    ) -> list[Fact]:
        """5.8: LRU 召回 — 按 last_accessed_ts ASC 取最久未访问的 top-k.

        用途:
            - 内存压力下淘汰冷数据 (k=待淘汰数)
            - 后台回写时优先选冷 fact 写远端
            - 用户做"最久没看过的记忆"复盘

        ``active_only=True`` 时只召回 archived=0; False 时含已归档.
        老行 (last_accessed_ts=0.0) 永远排最前, 适合做冷数据回收.

        Args:
            k: 返回条数上限.
            active_only: True=只取未归档 (默认), False=全部.

        Returns:
            list[Fact]: 按 last_accessed_ts ASC (最久未访问在前).
        """
        sql = "SELECT * FROM facts WHERE 1=1"
        params: list = []
        if active_only:
            sql += " AND archived = 0"
        sql += " ORDER BY last_accessed_ts ASC, ts ASC LIMIT ?"
        params.append(k)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]


    # ---- 5.10: TTL ----

    def set_expiry(
        self,
        fact_id: int,
        ttl_seconds: float,
    ) -> Fact | None:
        """5.10 新方法: 设置某条 fact 的 TTL, 返回更新后 Fact; id 不存在 → None。

        TTL 语义:
          * ``ttl_seconds > 0``  →  expires_ts = now + ttl_seconds
          * ``ttl_seconds <= 0`` →  expires_ts = NULL (永不过期, 即清除过期)

        与 :meth:`update_confidence` / :meth:`update_title` 返回类型对齐,
        都是 ``UPDATE + SELECT 回读完整 Fact``, 调用方拿到快照避免二次 recall。

        索引: ``set_expiry`` 改 expires_ts 后 partial index idx_facts_expires_ts
        会自动同步 (SQLite 在 UPDATE 时维护 partial index 谓词匹配的行)。

        Args:
            fact_id: 主键 id。
            ttl_seconds: 相对秒数; ``<= 0`` 表示清除过期 (``expires_ts=NULL``)。

        Returns:
            更新后的 :class:`Fact`; id 不存在时 ``None``。
        """
        if ttl_seconds and ttl_seconds > 0:
            new_expires = time.time() + float(ttl_seconds)
        else:
            new_expires = None
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE facts SET expires_ts = ? WHERE id = ?",
                (new_expires, fact_id),
            )
            if cur.rowcount == 0:
                return None
            row = self._conn.execute(
                "SELECT * FROM facts WHERE id = ?", (fact_id,)
            ).fetchone()
        return self._row_to_fact(row) if row else None

    def recall_unexpired(
        self,
        query: str = "",
        k: int = 5,
        category: str | None = None,
    ) -> list[Fact]:
        """5.10 新方法: 召回未过期 fact (走 idx_facts_expires_ts partial)。

        过滤条件:
          * ``archived = 0`` (与 :meth:`recall_active` 行为对齐)
          * ``(expires_ts IS NULL) OR (expires_ts >= now)``

        永不过期 (expires_ts IS NULL) 的 fact 永远纳入; 过期 fact
        (expires_ts < now) 排除 — 这与 ``archived`` 概念正交, 用户主动
        删过期 fact 走 :meth:`purge_expired`。

        Args:
            query: 可选 content LIKE 过滤; 空串不过滤。
            k: 返回条数上限, 默认 5。
            category: 可选 category 过滤; None 跨类。

        Returns:
            按 ts DESC 排序的未过期 Fact 列表。
        """
        now = time.time()
        sql = (
            "SELECT * FROM facts WHERE archived = 0 "
            "AND (expires_ts IS NULL OR expires_ts >= ?)"
        )
        params: list = [now]
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

    def purge_expired(self, now: float | None = None) -> int:
        """5.10 新方法: 删除所有已过期 fact (expires_ts < now 且非 NULL)。

        走 partial index idx_facts_expires_ts — WHERE expires_ts IS NOT NULL
        谓词与 partial index 谓词一致, SQLite 直接走索引扫描, 不需要全表。

        ``now`` 参数为可注入测试时间点; ``None`` 时取 ``time.time()``。
        ``archived`` 状态不影响本方法 — 即便 archived=1 的过期 fact 也一并删
        (归档与过期是两个正交维度, 归档只是"软删除", 过期才是真正可回收)。

        Args:
            now: 参考时间戳 (unix); ``None`` = ``time.time()``。
                主要用于测试 (把过期阈值往前调验证已过期行被清掉)。

        Returns:
            int: 被删除的行数 (rowcount)。
        """
        if now is None:
            now = time.time()
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM facts WHERE expires_ts IS NOT NULL AND expires_ts < ?",
                (now,),
            )
            return cur.rowcount

    # ---- 5.11: LFU (Least/Frequently Used) ----
    def recall_most_accessed(
        self,
        k: int = 10,
        active_only: bool = True,
        category: str | None = None,
    ) -> list[Fact]:
        """5.11 新方法: 召回访问次数最多的 fact (走 idx_facts_access_count_ts)。

        与 :meth:`recall_lru` (按 last_accessed_ts 排) 互补 ——
        LRU 区分"最近一次访问", LFU 区分"总访问热度"。两者可结合做
        复合策略, e.g. ``0.7 * (1 / age) + 0.3 * access_count``。

        Args:
            k: 返回条数上限, 默认 10。
            active_only: ``True`` (默认) 时排除 ``archived=1`` 行。
            category: 可选 category 过滤, ``None`` 不过滤。

        Returns:
            list[Fact]: 按 ``access_count DESC, ts DESC`` 排序的 Fact 列表;
            空库或全部过滤掉时返回 ``[]``。新写入行 ``access_count=0`` 也会
            被召回 (但排在最末尾, 因为 tie 时按 ts DESC)。
        """
        sql = "SELECT * FROM facts WHERE access_count >= 0 "
        params: list = []
        if active_only:
            sql += "AND archived = 0 "
        if category is not None:
            sql += "AND category = ? "
            params.append(category)
        sql += "ORDER BY access_count DESC, ts DESC LIMIT ?"
        params.append(k)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def recall_least_accessed(
        self,
        k: int = 10,
        active_only: bool = True,
        category: str | None = None,
    ) -> list[Fact]:
        """5.11 新方法: 召回访问次数最少的 fact (回收候选)。

        用于"冷数据回收" / "为新写入腾空间"策略: 优先 archive / 压缩
        长期未被访问的行。ORDER BY access_count ASC 让小计数的行排在前,
        配合 idx_facts_access_count_ts (SQLite 优化器可反向扫描)。

        Args:
            k: 返回条数上限, 默认 10。
            active_only: ``True`` (默认) 时排除 ``archived=1`` 行。
            category: 可选 category 过滤, ``None`` 不过滤。

        Returns:
            list[Fact]: 按 ``access_count ASC, ts DESC`` 排序的 Fact 列表;
            空库或全部过滤掉时返回 ``[]``。
        """
        sql = "SELECT * FROM facts WHERE access_count >= 0 "
        params: list = []
        if active_only:
            sql += "AND archived = 0 "
        if category is not None:
            sql += "AND category = ? "
            params.append(category)
        sql += "ORDER BY access_count ASC, ts DESC LIMIT ?"
        params.append(k)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def increment_access_count(
        self,
        fact_id: int,
        n: int = 1,
    ) -> Fact | None:
        """5.11 新方法: 原子累加 access_count (顺手刷新 last_accessed_ts)。

        与 :meth:`touch_fact` 不同 ——
        ``touch_fact`` 只刷时间戳不计数; 本方法计数+时间戳都更新, 用于
        "每次 recall / 命中 都应该被算一次访问"的场景。
        返回 ``Fact | None`` 与 update_title / update_confidence 一致,
        区分"不存在 (None)"和"更新成功 (Fact)"。

        Args:
            fact_id: 主键 id; 不存在 → ``None``。
            n: 累加值, 默认 1; 传负值表示"撤销访问" (很少用, 但允许)。

        Returns:
            Fact | None: 更新后的 Fact; ``id`` 不存在 → ``None``。
        """
        if n == 0:
            # 0 = no-op, 仍返回当前 Fact (便于"读"语义)
            row = self._conn.execute(
                "SELECT * FROM facts WHERE id = ?", (fact_id,)
            ).fetchone()
            return self._row_to_fact(row) if row else None
        with self._lock, self._conn:
            now = time.time()
            cur = self._conn.execute(
                "UPDATE facts SET access_count = access_count + ?, "
                "last_accessed_ts = ? WHERE id = ?",
                (n, now, fact_id),
            )
            if cur.rowcount == 0:
                return None
            row = self._conn.execute(
                "SELECT * FROM facts WHERE id = ?", (fact_id,)
            ).fetchone()
        return self._row_to_fact(row) if row else None

