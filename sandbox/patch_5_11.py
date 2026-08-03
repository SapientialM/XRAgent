"""One-shot patch: src/xragent/memory/manager.py 5.10 -> 5.11

Adds:
  - Fact.access_count: int = 0  (LFU counter, pair with last_accessed_ts)
  - facts.access_count INTEGER NOT NULL DEFAULT 0  column
  - idx_facts_access_count_ts  compound index (access_count DESC, ts DESC)
  - _migrate_v511()  schema upgrade
  - save_fact(..., access_count: int = 0) parameter + persistence
  - _row_to_fact maps access_count
  - recall_most_accessed(k, active_only, category) -> list[Fact]
  - recall_least_accessed(k, active_only, category) -> list[Fact]
  - increment_access_count(fact_id, n) -> Optional[Fact]
"""
from __future__ import annotations

import shutil
from pathlib import Path

PATH = Path("src/xragent/memory/manager.py")
ORIG = PATH.read_text(encoding="utf-8")

shutil.copy(PATH, PATH.with_suffix(".py.bak.5.10"))

new = ORIG

# 1. 顶部 docstring 5.10 行后加 5.11 行
old1 = "    5.10: +Fact.expires_ts; +idx_facts_expires_ts (partial);\n        +set_expiry(fact_id, ttl_seconds); +recall_unexpired; +purge_expired"
new1 = (
    old1
    + ";\n        +Fact.access_count; +idx_facts_access_count_ts;\n"
    + "        +recall_most_accessed / recall_least_accessed / increment_access_count (5.11)"
)
assert old1 in new, "anchor 1 missing"
new = new.replace(old1, new1, 1)

# 2. SCHEMA_VERSION
old2 = "SCHEMA_VERSION = 510  # 5.10"
new2 = "SCHEMA_VERSION = 511  # 5.11"
assert old2 in new, "anchor 2 missing"
new = new.replace(old2, new2, 1)

# 3. Fact dataclass: expires_ts 行后加 access_count
old3 = (
    "    expires_ts: Optional[float] = None  # 5.10: TTL 过期 unix 时间戳; None = 永不过期\n"
    "\n\nclass MemoryManager:"
)
new3 = (
    "    expires_ts: Optional[float] = None  # 5.10: TTL 过期 unix 时间戳; None = 永不过期\n"
    "    access_count: int = 0  # 5.11: 访问次数, 与 last_accessed_ts 配合做精确 LFU\n"
    "\n\nclass MemoryManager:"
)
assert old3 in new, "anchor 3 missing"
new = new.replace(old3, new3, 1)

# 4. _TABLE_DDL: expires_ts 列后加 access_count
old4 = (
    "        -- 5.10: TTL (NULL = 永不过期, 真实值 = unix 时间戳)\n"
    "        expires_ts      REAL\n"
    "    );\n"
)
new4 = (
    "        -- 5.10: TTL (NULL = 永不过期, 真实值 = unix 时间戳)\n"
    "        expires_ts      REAL,\n"
    "        -- 5.11: 访问计数 (LFU 精确化: 新行=0, 每次 recall/touch 累加)\n"
    "        access_count    INTEGER NOT NULL DEFAULT 0\n"
    "    );\n"
)
assert old4 in new, "anchor 4 missing"
new = new.replace(old4, new4, 1)

# 5. _INDEXES_DDL: idx_facts_expires_ts 行后加 idx_facts_access_count_ts
old5 = (
    '        "CREATE INDEX IF NOT EXISTS idx_facts_expires_ts "\n'
    '        "ON facts(expires_ts ASC) WHERE expires_ts IS NOT NULL",\n'
    "    ]\n"
)
new5 = (
    '        "CREATE INDEX IF NOT EXISTS idx_facts_expires_ts "\n'
    '        "ON facts(expires_ts ASC) WHERE expires_ts IS NOT NULL",\n'
    "        # 5.11: LFU 召回最常访问 (DESC 让 ORDER BY access_count DESC 走索引)\n"
    '        "CREATE INDEX IF NOT EXISTS idx_facts_access_count_ts "\n'
    '        "ON facts(access_count DESC, ts DESC)",\n'
    "    ]\n"
)
assert old5 in new, "anchor 5 missing"
new = new.replace(old5, new5, 1)

# 6. _migrate_all 末尾加 _migrate_v511
old6 = "        self._migrate_v510()  # 5.10: +expires_ts + TTL 索引 + 3 方法\n"
new6 = (
    old6
    + "        self._migrate_v511()  # 5.11: +access_count + LFU 索引 + 3 recall 方法\n"
)
assert old6 in new, "anchor 6 missing"
new = new.replace(old6, new6, 1)

# 7. _migrate_v510 闭合 + "# ---- CRUD ----" 前插入 _migrate_v511
old7 = (
    '                "CREATE INDEX IF NOT EXISTS idx_facts_expires_ts "\n'
    '                "ON facts(expires_ts ASC) WHERE expires_ts IS NOT NULL",\n'
    "            )\n"
    "\n"
    "    # ---- CRUD ----"
)
new7 = (
    '                "CREATE INDEX IF NOT EXISTS idx_facts_expires_ts "\n'
    '                "ON facts(expires_ts ASC) WHERE expires_ts IS NOT NULL",\n'
    "            )\n"
    "\n"
    "    # ---- 5.11 ----\n"
    "    def _migrate_v511(self) -> None:\n"
    '        """5.10 -> 5.11: facts +access_count (INTEGER DEFAULT 0);\n'
    "+idx_facts_access_count_ts.\n"
    "\n"
    "        access_count 默认 0 — 对历史存量行零侵入 (新写入不再 +1);\n"
    "        recall_most_accessed / recall_least_accessed 通过\n"
    "        WHERE access_count >= 0 自动覆盖存量行。\n"
    "        复合索引 (access_count DESC, ts DESC) 让 ORDER BY 直接走索引,\n"
    "        配合 WHERE 过滤 archived=0 时可与 idx_facts_active 共存\n"
    "        (SQLite 优化器按 cost 选 plan)。\n"
    "\n"
    "        三个方法 (recall_most_accessed / recall_least_accessed /\n"
    "        increment_access_count) 在类尾部添加, 此处仅做 DDL。\n"
    '        """\n'
    '        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()}\n'
    '        if "access_count" not in cols:\n'
    "            with self._lock, self._conn:\n"
    '                self._conn.execute(\n'
    '                    "ALTER TABLE facts ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0"\n'
    "                )\n"
    "        with self._lock, self._conn:\n"
    "            self._safe_create_index(\n"
    "                self._conn,\n"
    '                "CREATE INDEX IF NOT EXISTS idx_facts_access_count_ts "\n'
    '                "ON facts(access_count DESC, ts DESC)",\n'
    "            )\n"
    "\n"
    "    # ---- CRUD ----"
)
assert old7 in new, "anchor 7 missing"
new = new.replace(old7, new7, 1)

# 8. save_fact: 加 access_count 参数 + INSERT + Fact ctor
old8a = (
    "        expires_ts: Optional[float] = None,  # 5.10: TTL 过期时间 (unix)\n"
    "    ) -> Fact:\n"
)
new8a = (
    "        expires_ts: Optional[float] = None,  # 5.10: TTL 过期时间 (unix)\n"
    "        access_count: int = 0,  # 5.11: 初始访问计数 (默认 0)\n"
    "    ) -> Fact:\n"
)
assert old8a in new, "anchor 8a missing"
new = new.replace(old8a, new8a, 1)

old8b = (
    '                "INSERT INTO facts (ts, category, content, source_turn, source_turn_idx, "\n'
    '                "tags, priority, title, confidence, last_accessed_ts, expires_ts) "\n'
    '                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",\n'
    "                (\n"
    "                    ts,\n"
    "                    category,\n"
    "                    content,\n"
    "                    source_turn,\n"
    "                    source_turn_idx,\n"
    "                    tags_json,\n"
    "                    priority,\n"
    "                    title_eff,\n"
    "                    conf,\n"
    "                    last_access,\n"
    "                    expires_ts,\n"
    "                ),\n"
)
new8b = (
    '                "INSERT INTO facts (ts, category, content, source_turn, source_turn_idx, "\n'
    '                "tags, priority, title, confidence, last_accessed_ts, expires_ts, "\n'
    '                "access_count) "\n'
    '                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",\n'
    "                (\n"
    "                    ts,\n"
    "                    category,\n"
    "                    content,\n"
    "                    source_turn,\n"
    "                    source_turn_idx,\n"
    "                    tags_json,\n"
    "                    priority,\n"
    "                    title_eff,\n"
    "                    conf,\n"
    "                    last_access,\n"
    "                    expires_ts,\n"
    "                    access_count,\n"
    "                ),\n"
)
assert old8b in new, "anchor 8b missing"
new = new.replace(old8b, new8b, 1)

old8c = (
    "            last_accessed_ts=last_access,\n"
    "            expires_ts=expires_ts,\n"
    "        )\n"
)
new8c = (
    "            last_accessed_ts=last_access,\n"
    "            expires_ts=expires_ts,\n"
    "            access_count=access_count,\n"
    "        )\n"
)
assert old8c in new, "anchor 8c missing"
new = new.replace(old8c, new8c, 1)

# 9. _row_to_fact: 加 access_count=r["access_count"]
old9 = (
    "            last_accessed_ts=float(r[\"last_accessed_ts\"]),\n"
    "            expires_ts=r[\"expires_ts\"],\n"
    "        )\n"
)
new9 = (
    "            last_accessed_ts=float(r[\"last_accessed_ts\"]),\n"
    "            expires_ts=r[\"expires_ts\"],\n"
    "            access_count=int(r[\"access_count\"]),\n"
    "        )\n"
)
assert old9 in new, "anchor 9 missing"
new = new.replace(old9, new9, 1)

# 10. 类末尾追加 3 个新方法 (recall_most_accessed / recall_least_accessed / increment_access_count)
extra = '''

    # ---- 5.11: LFU (Least/Frequently Used) ----
    def recall_most_accessed(
        self,
        k: int = 10,
        active_only: bool = True,
        category: Optional[str] = None,
    ) -> list[Fact]:
        """5.11 新方法: 召回访问次数最多的 fact (走 idx_facts_access_count_ts)。

        与 :meth:`recall_lru` (按 last_accessed_ts 排) 互补 ——
        LRU 区分\"最近一次访问\", LFU 区分\"总访问热度\"。两者可结合做
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
        category: Optional[str] = None,
    ) -> list[Fact]:
        """5.11 新方法: 召回访问次数最少的 fact (回收候选)。

        用于\"冷数据回收\" / \"为新写入腾空间\"策略: 优先 archive / 压缩
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
    ) -> Optional[Fact]:
        """5.11 新方法: 原子累加 access_count (顺手刷新 last_accessed_ts)。

        与 :meth:`touch_fact` 不同 ——
        ``touch_fact`` 只刷时间戳不计数; 本方法计数+时间戳都更新, 用于
        \"每次 recall / 命中 都应该被算一次访问\"的场景。
        返回 ``Optional[Fact]`` 与 update_title / update_confidence 一致,
        区分\"不存在 (None)\"和\"更新成功 (Fact)\"。

        Args:
            fact_id: 主键 id; 不存在 → ``None``。
            n: 累加值, 默认 1; 传负值表示\"撤销访问\" (很少用, 但允许)。

        Returns:
            Optional[Fact]: 更新后的 Fact; ``id`` 不存在 → ``None``。
        """
        if n == 0:
            # 0 = no-op, 仍返回当前 Fact (便于\"读\"语义)
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
'''

new = new.rstrip() + extra + "\n"

PATH.write_text(new, encoding="utf-8")
print(f"PATCHED: {len(ORIG)} -> {len(new)} bytes")