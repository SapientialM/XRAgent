"""MemoryManager: 短期消息 + 长期 SQLite 事实。"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    # 5.5 -> 5.6: +title TEXT nullable; +idx_facts_title; Fact +title: str|None=None
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
    def _decode_tags(raw: str | None) -> list[str]:
        """把 SQLite tags 列的 JSON 字符串解码回 list[str]。空串 / 非法 JSON / 非 list 一律回退 ``[]``。

        Args:
            raw: ``SELECT tags`` 取到的字符串; 可能是 None / ``""`` / ``'[]'`` / 非法 JSON。
        Returns:
            list[str]: 解析后的 tag 列表; 失败时 ``[]``。
        """
        if not raw:
            return []
        try:
            v = json.loads(raw)
            return [str(x) for x in v] if isinstance(v, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def _encode_tags(tags: Iterable[str] | None) -> str:
        """把 list[str] 序列化成可存进 SQLite 的 JSON 字符串。

        Args:
            tags: 任意可迭代的字符串序列; ``None`` 视作空 list。
        Returns:
            str: ``json.dumps(..., ensure_ascii=False)`` 结果; 失败兜底 ``"[]"``。
        """
        if tags is None:
            return "[]"
        try:
            return json.dumps(list(tags), ensure_ascii=False)
        except (TypeError, ValueError):
            return "[]"

    @staticmethod
    def _row_to_fact(row: tuple[Any, ...]) -> Fact:
        """把 SELECT row tuple 解构成 Fact 实例, 列顺序对齐 :attr:`_FACT_COLUMNS`。

        Args:
            row: 长度 == 10 的 tuple; ``tags`` 列走 :meth:`_decode_tags`,
                ``archived`` 走 ``bool()`` 把 0/1 转 False/True。
        Returns:
            Fact: 完整字段填充的 dataclass 实例。
        """
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

    def __init__(self, db_path: Path | str | None = None) -> None:
        """构造 MemoryManager, 打开 SQLite 连接并跑完所有 schema 迁移。

        ``db_path=None`` 时读 ``settings.memory_db``。父目录自动 ``mkdir -p``。
        WAL + NORMAL 模式平衡吞吐与崩溃安全。所有 ``_migrate_v5x`` 顺序跑完
        后再建索引 (避免 ALTER 期间索引被锁)。

        Args:
            db_path: SQLite 文件路径; ``None`` 走 ``settings.memory_db``。
        """
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

    def _migrate_v51(self) -> None:
        """5.0 -> 5.1: 加 ``source_turn_idx`` INTEGER 可空列。幂等。"""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "source_turn_idx" not in cols:
            self._conn.execute("ALTER TABLE facts ADD COLUMN source_turn_idx INTEGER")
            self._conn.commit()

    def _migrate_v53(self) -> None:
        """5.2 -> 5.3: 加 ``priority`` NOT NULL DEFAULT 0, 老行回填 0。幂等。"""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "priority" in cols:
            return
        self._conn.execute(
            "ALTER TABLE facts ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
        )
        self._conn.execute("UPDATE facts SET priority = 0 WHERE priority IS NULL")
        self._conn.commit()

    def _migrate_v54(self) -> None:
        """5.3 -> 5.4: 加 ``tags`` TEXT DEFAULT '[]' 列, 老行回填 '[]'。幂等。"""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "tags" in cols:
            return
        self._conn.execute("ALTER TABLE facts ADD COLUMN tags TEXT DEFAULT '[]'")
        self._conn.execute("UPDATE facts SET tags = '[]' WHERE tags IS NULL")
        self._conn.commit()

    def _migrate_v55(self) -> None:
        """5.4 -> 5.5: 加 ``archived`` NOT NULL DEFAULT 0, 老行回填 0。幂等。"""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "archived" in cols:
            return
        self._conn.execute(
            "ALTER TABLE facts ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
        )
        self._conn.execute("UPDATE facts SET archived = 0 WHERE archived IS NULL")
        self._conn.commit()

    def _migrate_v56(self) -> None:
        """5.5 -> 5.6: 补 title 列 (nullable TEXT). 老行 title=NULL=未命名, 行为不变."""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "title" in cols:
            return
        self._conn.execute("ALTER TABLE facts ADD COLUMN title TEXT")
        self._conn.commit()

    def save_fact(
        self,
        category: str,
        content: str,
        source_turn: str = "",
        source_turn_idx: int | None = None,
        priority: int = 0,
        tags: Iterable[str] | None = None,
        title: str | None = None,
    ) -> Fact:
        """插入一条 fact (5.6 新增 title 参数, 默认 None; 旧调用方不传仍合法)。

        Args:
            category: fact 分类; recall 时按 category 过滤的主键之一。
            content: 实际内容; ``recall()`` 的 ``LIKE %query%`` 在此列扫描。
            source_turn: 产生这条 fact 的 turn 标识 (字符串)。
            source_turn_idx: 同上的整数版, 用于 ``recall_by_turn_idx``。
            priority: 0=普通, >0 高优; ``recall_high_priority`` 据此过滤。
            tags: 任意可迭代的字符串序列; 走 :meth:`_encode_tags` 序列化成 JSON。
            title: 5.6 新增短标签; ``None`` 表示未命名, ``recall_by_title`` 走索引。
        Returns:
            Fact: 新插入行的完整 dataclass, ``id`` 来自 ``lastrowid``。
        """
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
    def recall(self, query: str, k: int = 5, category: str | None = None) -> list[Fact]:
        """按 ``content LIKE %query%`` + 可选 category 召回最近 k 条。不过滤 archived。

        Args:
            query: 模糊匹配关键字; 空串表示不限内容。
            k: 最多返回条数, 默认 5。
            category: 精确 category 名; ``None`` 不限。
        Returns:
            list[Fact]: 按 ``ts DESC`` 排序的最新 k 条; 可能为空。
        """
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
        """按时间窗口召回, 端点 ``None`` 时开放。``k`` 默认 1000 比 recall 大得多。

        Args:
            start_ts: 起始时间戳 (含); ``None`` 不限。
            end_ts: 结束时间戳 (含); ``None`` 不限。
            category: 精确 category 过滤; ``None`` 不限。
            k: 上限条数, 默认 1000。
        Returns:
            list[Fact]: 按 ``ts DESC`` 排序的命中行; 同样含 archived 行。
        """
        sql = f"SELECT {self._FACT_COLS_SQL} FROM facts"
        clauses, params = [], []
        if start_ts is not None:
            clauses.append("ts >= ?"); params.append(start_ts)
        if end_ts is not None:
            clauses.append("ts <= ?"); params.append(end_ts)
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
        """按 ``content`` 严格相等聚合, 返回频次最高的 n 条 (``HAVING c >= min_count``)。

        Args:
            n: 返回条数上限, 默认 10。
            category: 可选 category 过滤; ``None`` 不限。
            min_count: 至少出现几次才纳入候选, 默认 2 (过滤一次性 fact)。
        Returns:
            list[tuple[str, int]]: ``(content, count)``, 按 count 降序 / 最近 ts 降序。
        """
        sql = "SELECT content, COUNT(*) AS c FROM facts"
        params = []
        if category:
            sql += " WHERE category = ?"; params.append(category)
        sql += " GROUP BY content HAVING c >= ? ORDER BY c DESC, MAX(ts) DESC LIMIT ?"
        params.extend([min_count, n])
        rows = self._conn.execute(sql, params).fetchall()
        return [(r[0], r[1]) for r in rows]

    def recall_by_turn_idx(self, turn_idx: int, k: int = 100) -> list[Fact]:
        """按 ``source_turn_idx`` 精确召回某个 turn 的所有 fact, 走 ``idx_facts_source_turn_idx``。

        Args:
            turn_idx: ``source_turn_idx`` 列的值, 通常是 turn 编号。
            k: 上限条数, 默认 100。
        Returns:
            list[Fact]: 按 ``ts DESC`` 排序的命中行。
        """
        rows = self._conn.execute(
            f"SELECT {self._FACT_COLS_SQL} FROM facts "
            "WHERE source_turn_idx = ? ORDER BY ts DESC LIMIT ?",
            (turn_idx, k),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def delete_by_turn_idx(self, turn_idx: int) -> int:
        """按 ``source_turn_idx`` 物理删除某个 turn 的所有 fact, 返回受影响行数。

        与 :meth:`archive_fact` 软删除不同: 这里直接 DELETE, 不走 archived 列。

        Args:
            turn_idx: ``source_turn_idx`` 列的值。
        Returns:
            int: SQLite ``cur.rowcount``, 即被删行数 (可能为 0)。
        """
        cur = self._conn.execute(
            "DELETE FROM facts WHERE source_turn_idx = ?", (turn_idx,)
        )
        self._conn.commit()
        return cur.rowcount

    def recall_high_priority(
        self,
        k: int = 10,
        category: str | None = None,
        min_priority: int = 1,
    ) -> list[Fact]:
        """按 ``priority >= min_priority`` + 可选 category 召回, 走 ``idx_facts_category_priority_ts``。

        Args:
            k: 返回条数上限, 默认 10。
            category: 可选 category 过滤; ``None`` 不限。
            min_priority: priority 下限, 默认 1 (即 priority>=1 算高优)。
        Returns:
            list[Fact]: 按 ``priority DESC, ts DESC`` 排序。
        """
        sql = f"SELECT {self._FACT_COLS_SQL} FROM facts WHERE priority >= ?"
        params = [min_priority]
        if category:
            sql += " AND category = ?"; params.append(category)
        sql += " ORDER BY priority DESC, ts DESC LIMIT ?"
        params.append(k)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def recall_by_tag(self, tag: str, k: int = 10) -> list[Fact]:
        """按 tag 模糊匹配 (LIKE '%"tag"%') 召回, 利用 tags 列 JSON 字符串结构定位元素边界。

        Args:
            tag: 要匹配的 tag 字符串; 空串直接返回 ``[]``。
            k: 上限条数, 默认 10。
        Returns:
            list[Fact]: 按 ``ts DESC`` 排序的命中行。
        """
        if not tag:
            return []
        sql = (
            f"SELECT {self._FACT_COLS_SQL} FROM facts WHERE tags LIKE ? "
            "ORDER BY ts DESC LIMIT ?"
        )
        rows = self._conn.execute(sql, (f'%"{tag}"%', k)).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def recall_by_title(self, title: str, k: int = 10) -> list[Fact]:
        """5.6 新方法: 按 title 精确匹配召回 (走 idx_facts_title).

        Args:
            title: 精确匹配的 title 字符串; 空串直接返回 ``[]``。
            k: 上限条数, 默认 10。
        Returns:
            list[Fact]: 按 ``ts DESC`` 排序的命中行。
        """
        if not title:
            return []
        rows = self._conn.execute(
            f"SELECT {self._FACT_COLS_SQL} FROM facts "
            "WHERE title = ? ORDER BY ts DESC LIMIT ?",
            (title, k),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def update_title(self, fact_id: int, new_title: str | None) -> Fact | None:
        """5.6 新方法: 更新 title 并返回更新后的 Fact | None.

        返回类型 Fact | None (None = id 不存在 / rowcount=0).
        与 archive_fact (返回 bool) 不同: 这里回填完整 Fact, 避免二次 recall 开销.
        new_title=None 表示清空 title.

        Args:
            fact_id: facts.id 主键。
            new_title: 新 title; ``None`` 表示清空。
        Returns:
            Fact | None: 成功返回更新后的完整 Fact; id 不存在返回 ``None``。
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

    def recent(self, n: int = 20) -> list[Fact]:
        """无过滤召回最近 n 条 fact, 走 ``idx_facts_ts``。

        Args:
            n: 返回条数上限, 默认 20。
        Returns:
            list[Fact]: 按 ``ts DESC`` 排序。
        """
        rows = self._conn.execute(
            f"SELECT {self._FACT_COLS_SQL} FROM facts ORDER BY ts DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def archive_fact(self, fact_id: int) -> bool:
        """软删除: 把 ``archived`` 置 1。幂等 — 已 archived 的行返回 False。

        Args:
            fact_id: facts.id 主键。
        Returns:
            bool: True 表示这次更新影响了 1 行 (从 0→1); False 表示本来
                就 archived / id 不存在。
        """
        cur = self._conn.execute(
            "UPDATE facts SET archived = 1 WHERE id = ? AND archived = 0",
            (fact_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def unarchive_fact(self, fact_id: int) -> bool:
        """恢复: 把 ``archived`` 置 0。幂等 — 已 active 的行返回 False。

        Args:
            fact_id: facts.id 主键。
        Returns:
            bool: True 表示这次更新影响了 1 行 (从 1→0); False 表示本来
                就 active / id 不存在。
        """
        cur = self._conn.execute(
            "UPDATE facts SET archived = 0 WHERE id = ? AND archived = 1",
            (fact_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def recall_active(self, query: str = "", k: int = 10, category: str | None = None) -> list[Fact]:
        """在 ``archived = 0`` 的行里按 ``content LIKE`` + category 召回, 走 ``idx_facts_active``。

        Args:
            query: 模糊匹配关键字; 空串表示不限内容。
            k: 上限条数, 默认 10。
            category: 精确 category 过滤; ``None`` 不限。
        Returns:
            list[Fact]: 按 ``ts DESC`` 排序, 仅含未软删行。
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
        """返回 ``archived = 0`` 的行数。走 ``idx_facts_active``。

        Returns:
            int: 未软删 fact 总数。
        """
        return self._conn.execute(
            "SELECT COUNT(*) FROM facts WHERE archived = 0"
        ).fetchone()[0]

    def count(self) -> int:
        """返回 facts 表的总行数 (含 archived)。

        Returns:
            int: fact 总数。
        """
        return self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    def close(self) -> None:
        """关闭底层 SQLite 连接。调用后本实例不应再使用。"""
        self._conn.close()

    def compress_if_needed(
        self,
        messages: list[Any],
        budget_tokens: int,
        target_ratio: float = 0.7,
    ) -> list[Any]:
        """如果 messages 超出 ``budget_tokens``, 走 :class:`SimpleCompression` 压缩。

        Args:
            messages: 当前 context 消息列表; 元素类型任意 (``Any``)。
            budget_tokens: context 预算 token 数。
            target_ratio: 压缩目标比例 (默认 0.7 = 压到预算的 70%)。
        Returns:
            list[Any]: 压缩后的消息列表; 未触发压缩时与输入一致。
        """
        from ..compression.simple import SimpleCompression
        return SimpleCompression(
            budget_tokens=budget_tokens, target_ratio=target_ratio
        ).compress(messages)
