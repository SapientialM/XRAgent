"""memory 工具。"""
from __future__ import annotations

from typing import Any

from ..memory.manager import Fact, MemoryManager


# LLM 工具调用层统一的下限/上限边界。3 个 recall 风格工具 (memory_recall /
# memory_recall_range / memory_top_frequent) 的 k/n/min_count 都走这一对
# 上下界兜底, 防止 LLM 传 0 / 负数 / 上百万这种"恶意或失控"的参数把
# 长期记忆一次性拉爆。定义在模块顶层方便测试 import 验证。
_K_LIMIT_MIN: int = 1
_K_LIMIT_MAX: int = 1000
_MIN_COUNT_LIMIT_MIN: int = 1
_MIN_COUNT_LIMIT_MAX: int = 10_000


def _clip_limit(
    value: Any,
    *,
    default: int,
    lo: int,
    hi: int,
) -> int:
    """把 LLM 传过来的"数字"参数安全地 clip 到 ``[lo, hi]``。

    LLM 工具调用的 k / n / min_count 常见踩坑:

      * 传 ``None`` 或缺失 → 用 ``default``
      * 传字符串 ``"5"`` / 浮点 ``5.0`` → ``int(...)`` 强转
      * 传 ``True`` / ``False`` → ``True`` 会被强转成 1, ``False`` 成 0
        (后者再 clip 到 lo); 视为"未指定, 走默认"略奇怪, 所以这里把
        bool 视作无效, 走 default
      * 传 ``0`` / 负数 → clip 到 ``lo``
      * 传超大正数 → clip 到 ``hi``
      * 抛 ``ValueError`` / ``TypeError`` 的输入 → 用 default (兜底)

    设计动机: 早期只有 ``memory_recall`` 写了 ``k_eff = max(1, min(int(k), 1000))``
    这行内联, 其它两个工具漏了, LLM 传 0 会拿到空结果、传 100000 会试图
    全表扫。抽到一处后 3 个工具行为统一, 测试也只需验一个 helper。

    Args:
        value: 任意输入 (LLM 工具参数为 ``Any``)。
        default: value 不可解析时使用的兜底值 (也是合法范围内的值)。
        lo: 下界 (含), 强转后小于 lo 一律夹到 lo。
        hi: 上界 (含), 强转后大于 hi 一律夹到 hi。

    Returns:
        落在 ``[lo, hi]`` 区间内的 int。
    """
    # bool 是 int 的子类, ``isinstance(True, int) is True``; 但
    # LLM 传 ``True`` 当数字几乎总是 bug, 单独排除。
    if value is None or isinstance(value, bool):
        value = default
    else:
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = default
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _fact_to_dict(fact: Fact) -> dict[str, Any]:
    """把 :class:`Fact` 序列化成 LLM-facing 字典 (4 个字段, 顺序锁定)。

    字段集 (``id`` / ``ts`` / ``category`` / ``content``) 是 LLM 工具契约
    的一部分, ``test_memory_tools.py`` 锁定; 加字段必须同步更新本函数 +
    加测试。``source_turn`` / ``source_turn_idx`` 是 5.0→5.1 DB 内部字段,
    不暴露给 LLM (审计场景走 ``recall_by_turn_idx`` 而不是 ``memory_*``)。

    抽出前 ``memory_recall`` 与 ``memory_recall_range`` 各写一份 4 字段
    字面 dict; 一处加键就漏另一处。
    """
    return {
        "id": fact.id,
        "ts": fact.ts,
        "category": fact.category,
        "content": fact.content,
    }


def memory_save(category: str, content: str) -> dict[str, Any]:
    """保存一条 fact 到长期记忆（SQLite）。

    Args:
        category: fact 分类标签（用于按类过滤 / top-N 频次统计）。
        content: fact 正文。允许中文 / emoji / 多行文本。

    Returns:
        ``dict[str, Any]``，LLM 工具契约字段：
            * ``ok`` (bool): 始终为 True（底层异常不在工具层兜底）
            * ``id`` (int): 新 fact 的数据库主键，供后续 update / delete 引用
    """
    m = MemoryManager()
    # 5.1: save_fact 返回 Fact 而非 int, 这里取 .id 兼容原 LLM-facing 接口。
    fact = m.save_fact(category=category, content=content, source_turn="agent")
    return {"ok": True, "id": fact.id}


def memory_recall_range(
    start_ts: float | None = None,
    end_ts: float | None = None,
    category: str | None = None,
    k: int = 1000,
) -> dict[str, Any]:
    """按时间窗口从长期记忆召回 fact（newest first）。

    与 ``memory_recall`` (关键词 LIKE) 互补 —— 本工具回答"什么时候说的"。
    ``start_ts`` / ``end_ts`` 任一为 ``None`` 都表示对应端开放。

    Args:
        start_ts: 下界时间戳（Unix seconds）；``None`` 表示 -∞。
        end_ts: 上界时间戳；``None`` 表示 +∞。
        category: 按分类过滤；``None`` 表示所有分类。
        k: 最多返回条数（按 ts 降序截断），默认 1000。
            LLM 传 0 / 负数会被夹到 1, 超过 1000 会被夹到 1000, 走
            :func:`_clip_limit` 统一兜底。

    Returns:
        ``dict[str, Any]``，LLM 工具契约字段：
            * ``ok`` (bool): 始终 True
            * ``count`` (int): 实际返回的 fact 数
            * ``facts`` (list[dict[str, Any]]): 每条含 ``id`` (int) / ``ts`` (float)
              / ``category`` (str) / ``content`` (str) 四个键 (序列化走
              :func:`_fact_to_dict`; 字段集与顺序是 LLM 契约, 测试锁定)
    """
    m = MemoryManager()
    # k 兜底: LLM 可能传 0 / 负数 / 字符串 / 巨大数; clip 到 [1, 1000]
    # 防止空结果或一次拉爆。统一走 _clip_limit, 行为与 memory_recall 对齐。
    k_eff: int = _clip_limit(k, default=1000, lo=_K_LIMIT_MIN, hi=_K_LIMIT_MAX)
    facts = m.recall_range(start_ts=start_ts, end_ts=end_ts, category=category, k=k_eff)
    return {
        "ok": True,
        "count": len(facts),
        "facts": [_fact_to_dict(f) for f in facts],
    }


def memory_top_frequent(
    n: int = 10,
    category: str | None = None,
    min_count: int = 2,
) -> dict[str, Any]:
    """按 content 频次降序返回 top-N（用于回答"用户反复说过的点是什么"）。

    Args:
        n: 最多返回条数，默认 10。
            LLM 传 0 / 负数会被夹到 1, 超过 1000 会被夹到 1000, 走
            :func:`_clip_limit` 统一兜底。
        category: 按分类过滤；``None`` 表示跨所有分类聚合。
        min_count: 最低出现次数（默认 2，过滤一次性噪音）；
            需要召回全部时显式传 ``min_count=1``。0 / 负数会被夹到 1,
            超过 10000 会被夹到 10000 (同走 :func:`_clip_limit`)。

    Returns:
        ``dict[str, Any]``，LLM 工具契约字段：
            * ``ok`` (bool): 始终 True
            * ``count`` (int): 实际返回条目数
            * ``top`` (list[dict[str, int]]): 每条含 ``content`` (str) + ``count`` (int)
    """
    m = MemoryManager()
    # n / min_count 都走 _clip_limit, 与另外两个 recall 工具行为一致。
    # 默认值通过 _clip_limit 的 default 槽传入, 避免重复字面 10 / 2。
    n_eff: int = _clip_limit(n, default=10, lo=_K_LIMIT_MIN, hi=_K_LIMIT_MAX)
    min_count_eff: int = _clip_limit(
        min_count, default=2, lo=_MIN_COUNT_LIMIT_MIN, hi=_MIN_COUNT_LIMIT_MAX
    )
    top = m.top_frequent(n=n_eff, category=category, min_count=min_count_eff)
    return {
        "ok": True,
        "count": len(top),
        "top": [{"content": c, "count": cnt} for c, cnt in top],
    }


def memory_recall(
    query: str = "",
    k: int = 5,
    category: str | None = None,
) -> dict[str, Any]:
    """关键词 LIKE 召回 fact（newest first），回答"我说过什么关于 X 的事"。

    与 ``memory_recall_range`` (时间窗口) 互补 —— 本工具回答"说过什么"。

    Args:
        query: 关键词，匹配 ``facts.content LIKE '%query%'``。空字符串表示
            退化为全量最新 k 条（等价于不传 WHERE 子句）。
        k: 最多返回条数，默认 5（关键词召回通常用于"补上下文"，不宜一次塞太多）。
            LLM 传 0 / 负数会被夹到 1, 超过 1000 会被夹到 1000, 走
            :func:`_clip_limit` 统一兜底。
        category: 按分类过滤；``None`` 表示跨类搜索。

    Returns:
        ``dict[str, Any]``，LLM 工具契约字段：
            * ``ok`` (bool): 始终 True
            * ``count`` (int): 实际返回的 fact 数
            * ``facts`` (list[dict[str, Any]]): 每条含 ``id`` (int) / ``ts`` (float)
              / ``category`` (str) / ``content`` (str) 四个键 (序列化走
              :func:`_fact_to_dict`; 字段集与顺序是 LLM 契约, 测试锁定)

    索引:
        走 ``idx_facts_category_ts`` (category 非空时) 或 ``idx_facts_ts`` (无 category
        时)，均能让 ``ORDER BY ts DESC LIMIT ?`` 提前结束。
    """
    m = MemoryManager()
    # k 兜底走 _clip_limit, 与 memory_recall_range / memory_top_frequent 行为一致。
    k_eff: int = _clip_limit(k, default=5, lo=_K_LIMIT_MIN, hi=_K_LIMIT_MAX)
    facts = m.recall(query=query, k=k_eff, category=category)
    return {
        "ok": True,
        "count": len(facts),
        "facts": [_fact_to_dict(f) for f in facts],
    }


def memory_recall_by_tag(
    tag: str,
    k: int = 10,
) -> dict[str, Any]:
    """按 tag 跨 category 横向召回 fact (newest first)。

    与三个 category 内 recall 工具互补 —— 本工具回答"打同样 tag 的事有哪些"。
    走底层 ``MemoryManager.recall_by_tag``, 命中 ``idx_facts_tags`` 索引
    (LIKE '%"tag"%' 模式), 按 ts DESC 排序。

    Args:
        tag: 目标 tag (精确匹配 tag 字符串, 大小写敏感)。空字符串 / ``None``
            时直接返回空结果 (底层 ``recall_by_tag`` 已防御, 避免 LIKE '%%'
            全表扫; wrapper 层额外检查让 LLM 调用更稳)。
        k: 最多返回条数, 默认 10。LLM 传 0 / 负数会被夹到 1, 超过 1000
            会被夹到 1000, 走 :func:`_clip_limit` 统一兜底 (与另外三个
            recall 工具行为一致)。

    Returns:
        ``dict[str, Any]``, LLM 工具契约字段:
            * ``ok`` (bool): 始终 True
            * ``count`` (int): 实际返回的 fact 数
            * ``facts`` (list[dict[str, Any]]): 每条含 5 个键 —— ``id`` / ``ts`` /
              ``category`` / ``content`` / ``tags``。前 4 个走 :func:`_fact_to_dict`
              (与另外三个 recall 工具形状对齐), ``tags`` 是 ``list[str]`` (本工具
              特有, 因 tag 是查询键, 把命中的全部 tag 返回给 LLM 让它看到上下文)。
              字段顺序: id → ts → category → content → tags (后置方便 LLM 解析)。
    """
    # tag 空值显式拦截: 防止 LLM 误传空字符串导致 LIKE '%%' 把全库拉出来
    # (虽然底层 recall_by_tag 也会拦截, 但 wrapper 层早返能省一次 DB 往返)。
    if not tag:
        return {"ok": True, "count": 0, "facts": []}
    m = MemoryManager()
    # k 兜底走 _clip_limit, 与 memory_recall / memory_recall_range /
    # memory_top_frequent 行为一致; default=10 与底层 manager 默认对齐。
    k_eff: int = _clip_limit(k, default=10, lo=_K_LIMIT_MIN, hi=_K_LIMIT_MAX)
    facts = m.recall_by_tag(tag=tag, k=k_eff)
    # 走 _fact_to_dict + 追加 tags (不破坏既有 4 字段契约, tags 单独后置)。
    out: list[dict[str, Any]] = []
    for f in facts:
        d = _fact_to_dict(f)
        d["tags"] = list(f.tags)  # 拷贝, 避免 LLM 拿到 manager 内部引用
        out.append(d)
    return {"ok": True, "count": len(facts), "facts": out}


# ============ title 系列 wrapper helpers (5.6) ============
# 两个 helper (／_parse_fact_id、／_validate_title) 是 ``memory_recall_by_title``
# 和 ``memory_update_title`` 的前置门; LLM 工具调用层强约束:
#   * fact_id 必须能 coerce 成正整数 (clip 后 ≥1) 才进 SQL
#   * new_title 必须是合法字符串 (或 None 表示清空) 否则 ok=False
# 单独抽出便于单元测试锁定边界 (test_memory_tools_title.py 验证).


_FACT_ID_MIN: int = 1
_FACT_ID_MAX: int = 10**18
_TITLE_MAX_LEN: int = 200


def _parse_fact_id(value: Any) -> int | None:
    """把 LLM 传过来的 fact_id 安全地 coerce 成 ``[1, 10**18]`` 区间内 int。

    与 :func:`_clip_limit` 行为对齐: 不可解析值一律 ``None`` (调用方 wrap 成
    ``ok=False`` 错误回执), 不抛异常 — 避免 LLM 工具调用路径出现 500。

    排除 ``bool`` ——  ``isinstance(True, int) is True`` (bool 是 int 子类),
    但 LLM 传 ``True`` 当 fact_id 几乎总是 bug, 与 ``_clip_limit`` 语义一致。

    Args:
        value: 任意输入 (None / bool / str / int / float / 容器 / 对象)。

    Returns:
        int (clip 后落在 ``[_FACT_ID_MIN, _FACT_ID_MAX]``) 或 ``None`` (不可解析)。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < _FACT_ID_MIN:
        return _FACT_ID_MIN
    if n > _FACT_ID_MAX:
        return _FACT_ID_MAX
    return n


def _validate_title(value: Any) -> str | None:
    """校验 ``new_title`` 参数合法性; 合法返回 ``None``, 非法返回错误文案。

    错误文案刻意带"空白"/"字符串"/"200"这类关键字, 让 LLM 看到立刻知道
    错在哪 (``test_validate_title_*`` 测试锁定文案)。

    Args:
        value: 任意输入。``None`` 是**非法**输入 (清空语义走 wrapper 层,
            不是 validate 层的职责); 这里一律拒绝任何非 str。

    Returns:
        ``None`` 表示合法 (合法 str), 否则返回错误文案 (str)。
        Wrapper (:func:`memory_update_title`) 在调本 helper 前先单独
        处理 ``None`` (清空) 分支。
    """
    if not isinstance(value, str):
        return "title 必须是字符串"
    if not value.strip():
        return "title 不能是空串或纯空白"
    if len(value) > _TITLE_MAX_LEN:
        return f"title 长度不能超过 {_TITLE_MAX_LEN}"
    return None


# ============ LLM-facing wrappers (5.6) ============


def memory_recall_by_title(
    title: Any = "",
    k: int = 10,
) -> dict[str, Any]:
    """按 title 精确匹配召回 fact (newest first); 空 / 全空白 title 早返 ``[]``。

    与 ``memory_recall_by_tag`` 同设计套路: 横向 (跨 category) + 后置本工具特有字段。
    ``title="a"`` 不会召回 ``title="alpha"`` (与 LIKE 模糊区分) — 适合"我要找一条
    已知 fact"的修复场景; 模糊召回应走 ``memory_recall`` (关键词 LIKE content)。

    Args:
        title: 精确等值的 title 字符串。``""`` / 纯空白 / ``None`` 一律早返 ``[]``
            (不查 DB, 避免 LIKE '%%' 全表扫)。
        k: 最多返回条数, 默认 10。LLM 传 0 / 负数会被夹到 1, 超过 1000
            会被夹到 1000 (走 :func:`_clip_limit`, 与另外 3 个 recall 工具一致)。

    Returns:
        ``dict[str, Any]``:
            * ``ok`` (bool): 始终 True
            * ``count`` (int): 实际返回 fact 数
            * ``facts`` (list[dict]): 每条 5 字段 (id/ts/category/content/title),
              字段顺序锁定 — 测试 / LLM 契约强约束。
    """
    if not title or (isinstance(title, str) and not title.strip()):
        return {"ok": True, "count": 0, "facts": []}
    m = MemoryManager()
    k_eff: int = _clip_limit(k, default=10, lo=_K_LIMIT_MIN, hi=_K_LIMIT_MAX)
    facts = m.recall_by_title(title=str(title), k=k_eff)
    out: list[dict[str, Any]] = []
    for f in facts:
        d = _fact_to_dict(f)
        d["title"] = f.title
        out.append(d)
    return {"ok": True, "count": len(facts), "facts": out}


def memory_update_title(
    fact_id: Any,
    new_title: Any = None,
) -> dict[str, Any]:
    """更新某条 fact 的 title; ``new_title=None`` 表示清空, 非法输入返回 ``ok=False``。

    三层校验顺序:
      1. ``_parse_fact_id`` 拒不可 coerce 值 (None / bool / 字符串 "abc" / 容器)
      2. ``_validate_title`` 拒空 / 纯空白 / 非字符串 (>200) — ``None`` 是合法清空
      3. ``MemoryManager.update_title`` 改 DB; rowcount=0 → ok=False "fact 不存在"

    Args:
        fact_id: 主键 id, 接受 int / 数字字符串 / float (走 :func:`_parse_fact_id` 强转)。
        new_title: 新 title; ``None`` 清空, 字符串走 ``str.strip()`` 后写入。

    Returns:
        ``dict[str, Any]``:
            成功: ``{"ok": True, "id": <int>, "new_title": <str|None>,
                    "fact": {5 字段 Fact 快照}}``
            失败: ``{"ok": False, "error": <str>``} (fact_id 非法 / 不存在 /
                  title 非法 三类, error 文案锁定供 LLM 自检)。
    """
    parsed_id = _parse_fact_id(fact_id)
    if parsed_id is None:
        return {"ok": False, "error": f"fact_id 非法: {fact_id!r}"}
    # ``None`` 是合法清空, 走 manager.update_title 分支 (列置 "");
    # 其他非 str 不在这里兜底 (_validate_title 拒它), 因为 manager 的
    # update_title 不接受非字符串 → 避免 dtype drift.
    if new_title is not None:
        title_err = _validate_title(new_title)
        if title_err is not None:
            return {"ok": False, "error": title_err}
    new_title_eff: str | None = (
        None if new_title is None else str(new_title).strip()
    )
    m = MemoryManager()
    fact = m.update_title(parsed_id, new_title_eff)
    if fact is None:
        return {
            "ok": False,
            "error": f"fact 不存在 (id={parsed_id})",
        }
    # manager.update_title 把 None 收敛为空串 (NOT NULL DEFAULT '' 列),
    # wrapper 返回值用 ``new_title_eff`` 反映用户传入语义, 而不是 DB 物理值.
    return {
        "ok": True,
        "id": fact.id,
        "new_title": new_title_eff,
        "fact": {
            "id": fact.id,
            "ts": fact.ts,
            "category": fact.category,
            "content": fact.content,
            "title": new_title_eff,
        },
    }
