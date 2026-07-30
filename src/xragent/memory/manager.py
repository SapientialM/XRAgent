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
    # 5.1: 新增字段，对应 DB 列 source_turn_idx (INTEGER, nullable)。
    # 与 source_turn (TEXT, turn id 字符串) 并存: 字符串给人看, 整数给索引。
    # 新字段放在末尾 + 默认 None, 老代码 positional 构造 5 个字段不会破坏。
    source_turn_idx: int | None = None
    # 5.3: 新增字段，对应 DB 列 priority (INTEGER NOT NULL DEFAULT 0)。
    # 配合 recall_high_priority() 用: 让"高重要级 fact 优先"成为一等公民。
    # 与 source_turn_idx 同样是末尾 + 默认值, 老代码构造 5 字段不受影响。
    # 默认 0 表示"未标重要级", recall_high_priority 默认 min_priority=1 过滤掉。
    priority: int = 0
    # 5.4: 新增字段，对应 DB 列 tags (TEXT, JSON 数组字符串)。
    # 与 category (单一分类) 互补: category 走主分类轴 (preference/history),
    # tags 走横向主题轴 (python/typed/cli)。list[str] 比单 category 表达力强。
    # 末尾 + 默认空 list, 老代码构造不受影响。
    tags: list[str] = field(default_factory=list)


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

    # === Schema 版本: 5.1 → 5.2 ===
    # 变更:
    #   1. 新增方法 delete_by_turn_idx(turn_idx) -> int
    # 用途:
    #   - 配合 snapshot 回滚: "撤销第 N 轮" 时把该 turn 写入的 fact 一起清掉,
    #     避免下次 recall 又召回已撤销的事实
    # 兼容性:
    #   - schema 0 改动 (不需 migration)
    #   - 走 idx_facts_source_turn_idx 索引 O(log n) (5.1 已建, 复用)
    #   - 新方法对老调用方零影响 (新增, 不替换任何现有方法)

    # === Schema 版本: 5.2 → 5.3 ===
    # 变更:
    #   1. facts 表新增列 priority INTEGER NOT NULL DEFAULT 0
    #   2. 新增索引 idx_facts_category_priority_ts
    #        ON facts(category, priority DESC, ts DESC)
    #   3. 新增方法 recall_high_priority(k, category, min_priority) -> list[Fact]
    #   4. Fact dataclass 末尾新增 priority: int = 0 字段
    # 用途:
    #   - 让"按 priority 排序召回"成为可能 (重要 fact 不被海量 history 淹没)
    #   - 复合索引走 recall_high_priority(category=?) O(log n) 路径
    # 向后兼容:
    #   - 老行 ALTER 后会被 UPDATE 回填 priority=0 (保险, 见 _migrate_v53)
    #   - 新 DB 走 BASE_SCHEMA 直接含新列 + DEFAULT 0
    #   - save_fact() 新参数 priority: int = 0, 老调用零影响
    # 索引选择理由:
    #   - recall_high_priority(category=?) 主路径:
    #       WHERE category=? AND priority>=?
    #       ORDER BY priority DESC, ts DESC LIMIT k
    #   - 复合 (category, priority DESC, ts DESC) 让 SQLite:
    #       a) category 等值过滤做 index seek
    #       b) priority DESC + ts DESC 已是索引顺序, ORDER BY 零成本
    #       c) LIMIT 提前结束扫描
    #   - 单列 idx_facts_priority 不够: WHERE category=? 仍要 row filter

    # === Schema 版本: 5.3 → 5.4 ===
    # 变更:
    #   1. facts 表新增列 tags TEXT (JSON 数组字符串, 默认 '[]')
    #   2. 新增索引 idx_facts_tags ON facts(tags)
    #   3. 新增方法 recall_by_tag(tag, k) -> list[Fact]
    #   4. Fact dataclass 末尾新增 tags: list[str] = field(default_factory=list)
    #   5. save_fact() 新参数 tags: list[str] | None = None
    # 用途:
    #   - category 是单分类 (preference/history), tags 是多标签横向主题
    #     (python/typed/cli)。同一 fact 可同时跨多主题被召回。
    #   - recall_by_tag("python") 可一次性跨 category 拉所有相关 fact,
    #     这是单 category 索引做不到的
    # 设计选择: 为什么 tags 存 JSON 字符串而不是单独 tags 表?
    #   - 单独 tags 表需要 (fact_id, tag) JOIN, 写路径加 1 次 INSERT
    #   - recall_by_tag 单查路径, 不需要聚合 / 排序 by tag
    #   - JSON 字符串 LIKE 配引号包裹精确匹配: WHERE tags LIKE '%"tag"%'
    #     走 idx_facts_tags 索引 (B-tree on TEXT), 不会误匹配子串
    #     (例: 查 "py" 不会匹配 '["python"]', 因为 'python' 前后是引号)
    # 向后兼容:
    #   - 新列 nullable + DEFAULT '[]'; 老行 ALTER 后回填 tags='[]'
    #   - save_fact() 新参数 tags 默认 None (→ 存 '[]'), 老调用零影响
    #   - _row_to_fact 多读 row[7], 反序列化失败回退 [] (不抛, 不阻塞 recall)
    # 索引选择:
    #   - idx_facts_tags 单列 B-tree; LIKE '%"x"%' 实际是 "前导% + 精确 + 后缀"
    #     的常见模式, SQLite LIKE 优化在尾缀为常量时仍可走索引
    #     (见 https://sqlite.org/optoverview.html#like_optimization)。
    #     小数据集上退化为全表扫也可接受, 因为 fact 表预期 < 10k 行。
    #   - 不建 (category, tags) 复合: recall_by_tag 不需要 category 协同过滤,
    #     当前用例都是"跨 category 找主题"

    BASE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS facts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts REAL NOT NULL,
      category TEXT NOT NULL,
      content TEXT NOT NULL,
      source_turn TEXT,
      source_turn_idx INTEGER,
      priority INTEGER NOT NULL DEFAULT 0,
      tags TEXT DEFAULT '[]'
    );
    """

    INDEX_SCHEMA = """
    CREATE INDEX IF NOT EXISTS idx_facts_category_ts ON facts(category, ts DESC);
    CREATE INDEX IF NOT EXISTS idx_facts_ts ON facts(ts DESC);
    CREATE INDEX IF NOT EXISTS idx_facts_source_turn ON facts(source_turn);
    CREATE INDEX IF NOT EXISTS idx_facts_source_turn_idx ON facts(source_turn_idx);
    CREATE INDEX IF NOT EXISTS idx_facts_category_priority_ts ON facts(category, priority DESC, ts DESC);
    CREATE INDEX IF NOT EXISTS idx_facts_tags ON facts(tags);
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
    #    5.2 起还支撑 delete_by_turn_idx() 的 O(log n) 删除。
    # 5. (category, priority DESC, ts DESC): 5.3 新增, 配合 recall_high_priority。
    #    是 idx_facts_category_ts 的"超集" (priority 永远追加在 ts 前), 但因为
    #    排序不同 (priority DESC vs ts DESC), 不能复用, 必须独立索引。
    # 6. (tags): 5.4 新增, 配合 recall_by_tag()。LIKE '%"tag"%' 在 SQLite
    #    走索引的优化路径需要 LIKE 后缀为常量; 小数据集退化为全表扫可接受。
    # 7. Old single-column idx_facts_category is a prefix of the composite and is
    #    therefore redundant; existing DBs may still carry it (harmless).

    # SELECT 投影顺序约定：所有 SELECT 都要按这个 tuple 顺序输出, _row_to_fact 才能
    # 用 fixed indices 还原 Fact。新加列必须追加在末尾 + 同步更新本约定。
    # 5.3: 末尾追加 priority。
    # 5.4: 末尾追加 tags (JSON 字符串, 反序列化为 list[str])。
    _FACT_COLUMNS = ("id", "ts", "category", "content", "source_turn", "source_turn_idx", "priority", "tags")

    @staticmethod
    def _decode_tags(raw: str | None) -> list[str]:
        """DB tags TEXT → list[str]。失败回退 [], 不抛 (recall 路径稳定优先)。"""
        if not raw:
            return []
        try:
            v = json.loads(raw)
            return [str(x) for x in v] if isinstance(v, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def _encode_tags(tags: list[str] | None) -> str:
        """list[str] → DB tags TEXT。None → '[]'。JSON 失败回退 '[]'。"""
        if tags is None:
            return "[]"
        try:
            return json.dumps(list(tags), ensure_ascii=False)
        except (TypeError, ValueError):
            return "[]"

    @staticmethod
    def _row_to_fact(row: tuple) -> Fact:
        """DB 行 → Fact 还原。``_FACT_COLUMNS`` 是投影顺序契约, 改 SELECT 时同步改。

        抽到此处前 4 个召回方法 (recall/recall_range/recall_by_turn_idx/recent) 各写
        一份 7 行 ``Fact(id=r[0], ts=r[1], ...)``, 加列时容易漏一处; 集中后只改一处。
        5.3: 末尾多读 row[6] = priority。
        5.4: 末尾多读 row[7] = tags (JSON 字符串, 反序列化为 list[str])。
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
        self._migrate_v53()
        self._migrate_v54()
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

    def _migrate_v53(self) -> None:
        """5.2 → 5.3: 为已存在的 facts 表补 priority 列 + 老行回填。

        三步:
          1. PRAGMA table_info 探列; 已存在直接 return (幂等)
          2. ALTER TABLE ADD COLUMN priority INTEGER NOT NULL DEFAULT 0
          3. UPDATE facts SET priority = 0 WHERE priority IS NULL  (老行回填)

        SQLite 自 3.31.0 (2020-01) 起, ALTER TABLE ADD COLUMN ... DEFAULT 会
        自动回填老行为 DEFAULT; 但早于该版本的行为是"schema 写 DEFAULT, 但老
        行实际值是 NULL"。显式 UPDATE 是保险, 1 行 SQL 代价低, 也让
        recall_high_priority WHERE priority >= 1 的语义对老数据自然成立
        (NULL >= 1 在 SQLite 是 NULL, 不匹配)。
        """
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "priority" in cols:
            return
        self._conn.execute(
            "ALTER TABLE facts ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
        )
        # 老行回填 (兼容 pre-3.31 SQLite)
        self._conn.execute("UPDATE facts SET priority = 0 WHERE priority IS NULL")
        self._conn.commit()

    def _migrate_v54(self) -> None:
        """5.3 → 5.4: 为已存在的 facts 表补 tags 列 + 老行回填 '[]'。

        三步:
          1. PRAGMA table_info 探列; 已存在直接 return (幂等)
          2. ALTER TABLE ADD COLUMN tags TEXT DEFAULT '[]'
          3. UPDATE facts SET tags = '[]' WHERE tags IS NULL  (老行回填)

        与 _migrate_v53 同款保险: SQLite 3.31.0+ 自动回填 DEFAULT, 早于此版本
        老行实际为 NULL。recall_by_tag 走 LIKE '%"x"%', NULL 不匹配是正确语义。
        """
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "tags" in cols:
            return
        self._conn.execute(
            "ALTER TABLE facts ADD COLUMN tags TEXT DEFAULT '[]'"
        )
        # 老行回填 (兼容 pre-3.31 SQLite)
        self._conn.execute("UPDATE facts SET tags = '[]' WHERE tags IS NULL")
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
        """插入一条 fact, 返回刚插入的 Fact 对象 (含 db 自增 id 与 ts)。

        返回类型 5.0→5.1 由 int 改为 Fact:
          - 老调用方关心 id: 改用 .id
          - 顺便拿到 ts / category / content, 不必再 recall 一次
        5.3: 新参数 priority: int = 0, 老调用零影响。
        5.4: 新参数 tags: list[str] | None = None, 序列化后存 tags TEXT。
        """
        ts = time.time()
        tags_json = self._encode_tags(tags)
        cur = self._conn.execute(
            "INSERT INTO facts (ts, category, content, source_turn, source_turn_idx, priority, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, category, content, source_turn, source_turn_idx, priority, tags_json),
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
            priority=priority,
            tags=list(tags) if tags else [],
        )

    def recall(self, query: str, k: int = 5, category: str | None = None) -> list[Fact]:
        sql = (
            "SELECT id, ts, category, content, source_turn, source_turn_idx, priority, tags "
            "FROM facts"
        )
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
        sql = (
            "SELECT id, ts, category, content, source_turn, source_turn_idx, priority, tags "
            "FROM facts"
        )
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
            "SELECT id, ts, category, content, source_turn, source_turn_idx, priority, tags "
            "FROM facts WHERE source_turn_idx = ? "
            "ORDER BY ts DESC LIMIT ?",
            (turn_idx, k),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def delete_by_turn_idx(self, turn_idx: int) -> int:
        """按 turn 整数索引删除 fact。5.2 新方法。

        配合 snapshot 回滚场景: 撤销某 turn 时把它的全部 fact 视为副作用一并清除,
        避免下次 recall 又召回已撤销的事实。走 idx_facts_source_turn_idx 索引 (5.1
        已建) 做 O(log n) 删除。

        不存在的 turn_idx 走索引扫描后无匹配, 返回 0 (非异常, 非 None)。

        Args:
            turn_idx: turn 的整数索引, 同 :meth:`save_fact` 的 ``source_turn_idx``。

        Returns:
            被删除的行数。0 表示该 turn_idx 无 fact 或已被删干净。
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
        """按 priority DESC, ts DESC 排序召回。5.3 新方法。

        索引命中: idx_facts_category_priority_ts (5.3 新建)。
          - 有 category 时: index seek (category, priority, ts) 走完整索引
          - 无 category 时: 退化为 priority 上的 range scan, 仍优于全表
        ORDER BY priority DESC, ts DESC 让 LIMIT 提前结束。

        默认 min_priority=1 排除 priority=0 的默认行, 只返回显式标过重要级的
        fact; 想召回全部 priority=0 时显式传 min_priority=0。

        Args:
            k: 返回条数, 默认 10。
            category: 可选 category 过滤; 传了走复合索引, 不传走单维排序。
            min_priority: 召回的 priority 下限, 默认 1 (排除默认行)。

        Returns:
            按 priority DESC, ts DESC 排序的 Fact 列表。
        """
        sql = (
            "SELECT id, ts, category, content, source_turn, source_turn_idx, priority, tags "
            "FROM facts WHERE priority >= ?"
        )
        params: list = [min_priority]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY priority DESC, ts DESC LIMIT ?"
        params.append(k)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def recall_by_tag(self, tag: str, k: int = 10) -> list[Fact]:
        """按 tag 召回 fact。5.4 新方法。

        跨 category 横向召回, 例如 recall_by_tag("python") 同时拉
        preference/history/note 任何 category 下打了 "python" 标签的 fact。

        查询模式: WHERE tags LIKE '%"tag"%'
          - JSON 数组里每个元素都有引号包裹, 精确匹配 "python" 不会误匹配
            "pythonic" 或 "cpython"
          - 走 idx_facts_tags 索引 (B-tree on TEXT, LIKE 后缀为常量时 SQLite
            走索引优化路径, 见 https://sqlite.org/optoverview.html#like_optimization)
          - 顺序按 ts DESC, LIMIT 提前结束

        Args:
            tag: 单个 tag, 不含引号 (内部加引号)。
            k: 返回条数, 默认 10。

        Returns:
            按 ts DESC 排序的 Fact 列表。空 tag 返回 []。
        """
        if not tag:
            return []
        sql = (
            "SELECT id, ts, category, content, source_turn, source_turn_idx, priority, tags "
            "FROM facts WHERE tags LIKE ? "
            "ORDER BY ts DESC LIMIT ?"
        )
        # 引号包裹避免子串误匹配; LIKE pattern 用 ESCAPE 子句没必要因为
        # 我们控制的字符串 (来自 save_fact 调用方) 不含特殊 LIKE 元字符
        rows = self._conn.execute(sql, (f'%"{tag}"%', k)).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def recent(self, n: int = 20) -> list[Fact]:
        rows = self._conn.execute(
            "SELECT id, ts, category, content, source_turn, source_turn_idx, priority, tags "
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
