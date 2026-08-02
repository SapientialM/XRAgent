，或 ``None`` 表示不可解析 (调用方
    应 wrap 成 ``ok=False`` 错误回执)。

    设计动机: 与 :func:`_clip_limit` 共用一套语义 ("None / 不可解析 → 兜底
    值"), 但 ``_clip_limit`` 的兜底是 ``default`` (一个合法 int), 而本
    helper 的兜底是 ``None`` (调用方需要区分 "不可解析" vs "正常 clip")。

    Examples:
        >>> _parse_fact_id(7)
        7
        >>> _parse_fact_id("42")
        42
        >>> _parse_fact_id(-3)  # 夹到下界
        1
        >>> _parse_fact_id("not a number")  # 不可解析
        None
        >>> _parse_fact_id(True)  # bool 视作不可解析
        None
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    if v < _FACT_ID_MIN:
        return _FACT_ID_MIN
    if v > _FACT_ID_MAX:
        return _FACT_ID_MAX
    return v


def _validate_title(new_title: Any) -> str | None:
    """校验 LLM 传入的 new_title 是否合法 (返回一个 union 或抛 ``ValueError``)。

    返回值语义:
        * ``str`` (空串或非空) → 合法, 调用方直接写入 DB
        * ``None`` → 合法, 表示"清空 title" (5.6 schema 允许 title IS NULL)
        * 抛 ``ValueError`` → 非法 (LLM 传 int / list / dict / bool / 超长字符串)

    校验规则:
        * 必须是 ``str`` 或 ``None`` (literal), 其它类型 (``int`` / ``list`` /
          ``dict`` / ``bool``) 一律抛 ``ValueError``
        * ``str`` 必须 strip 后长度 ≤ ``_TITLE_MAX_LEN`` (200); 超长抛 ``ValueError``
        * ``None`` 通过 (literal None 区分"清空"vs"不传"; LLM 传 None 表示
          明确要清空)
        * ``bool`` 视为非法 (与 :func:`_parse_fact_id` 一致, 避免
          ``isinstance(True, int) is True`` 类的隐式转换)

    Args:
        new_title: 任意输入 (LLM 工具参数 ``Any``)。

    Returns:
        ``str | None``: 合法返回值 (``str`` 或 ``None``); 非法抛 ``ValueError``。

    为什么用抛异常而不是返回 ``False``: 调用方 (``memory_update_title``)
    需要在每个失败点 wrap 成结构化错误回执; 用异常能把"非法"的逻辑集中
    在一个 try/except, 调用方不必每次手动 ``if x is False``。返回 union
    (``str | None``) 让成功路径的 mypy 收窄不需 ``cast``。
    """
    if new_title is None:
        return None
    if isinstance(new_title, bool):
        # bool 是 str 子类? 不是; 但 isinstance(True, int) is True
        # —— 这里专门排除, 避免 LLM 误传 True 当 title。
        raise ValueError("new_title 必须是 str 或 None, bool 不合法")
    if not isinstance(new_title, str):
        raise ValueError(f"new_title 类型非法: {type(new_title).__name__}")
    # strip 后超长 → 抛异常; 不 strip 直接看长度也可, 这里 strip 让 LLM 传
    # " " 这类"视觉空格"也能被校验掉 (只是首尾空白语义上不算 title)。
    if len(new_title.strip()) > _TITLE_MAX_LEN:
        raise ValueError(
            f"new_title 过长 (strip 后 > {_TITLE_MAX_LEN} 字符)"
        )
    return new_title


def memory_recall_by_title(
    title: str,
    k: int = 10,
) -> dict[str, Any]:
    """按 title 精确匹配召回 fact (newest first)。

    与 ``memory_recall`` (关键词 LIKE / 内容) 和 ``memory_recall_by_tag``
    (跨 category tag) 互补 —— 本工具回答"标题叫 X 的事有哪些"。
    走底层 ``MemoryManager.recall_by_title``, 命中 ``idx_facts_title`` 索引
    (title IS NOT NULL WHERE title = ? ORDER BY ts DESC LIMIT ?), 因 title
    是 schema 强约束 NOT NULL + 等值匹配, 索引能完全消解 ORDER BY。

    Args:
        title: 精确等值的 title 字符串 (与底层 ``recall_by_title`` 一致)。
            空字符串 / ``None`` / 纯空白直接返回空结果 (底层已防御,
            wrapper 层早返省一次 DB 往返)。
        k: 最多返回条数, 默认 10。LLM 传 0 / 负数会被夹到 1, 超过 1000
            会被夹到 1000, 走 :func:`_clip_limit` 统一兜底 (与另外三个
            recall 工具行为一致)。

    Returns:
        ``dict[str, Any]``, LLM 工具契约字段:
            * ``ok`` (bool): 始终 True
            * ``count`` (int): 实际返回的 fact 数
            * ``facts`` (list[dict[str, Any]]): 每条含 5 个键 —— ``id`` / ``ts`` /
              ``category`` / ``content`` / ``title``。前 4 个走 :func:`_fact_to_dict`
              (与另外三个 recall 工具形状对齐), ``title`` 是 ``str`` 或 ``None``
              (本工具特有, 因 title 是查询键, 把命中的 title 显式回显; 对应
              schema 允许 ``title IS NULL`` 的情况)。
              字段顺序: id → ts → category → content → title (后置方便 LLM 解析)。
    """
    # title 空值显式拦截: LLM 误传空字符串 / 纯空白, 底层 recall_by_title
    # 已防御 (返回 []), wrapper 层早返能省一次 DB 往返。
    if not title or not title.strip():
        return {"ok": True, "count": 0, "facts": []}
    m = MemoryManager()
    # k 兜底走 _clip_limit, 与 memory_recall / memory_recall_range /
    # memory_top_frequent / memory_recall_by_tag 行为一致;
    # default=10 与底层 manager 默认对齐。
    k_eff: int = _clip_limit(k, default=10, lo=_K_LIMIT_MIN, hi=_K_LIMIT_MAX)
    facts = m.recall_by_title(title=title, k=k_eff)
    # 走 _fact_to_dict extras= 追加 title (不破坏既有 4 字段契约, title 单独后置);
    # 不拷 .title 引用 —— ``str | None`` 是不可变值, LLM 拿到原引用也无副作用。
    return {
        "ok": True,
        "count": len(facts),
        "facts": [_fact_to_dict(f, extras={"title": f.title}) for f in facts],
    }


def memory_update_title(
    fact_id: int,
    new_title: str,
) -> dict[str, Any]:
    """更新某条 fact 的 title; ``new_title`` 传 ``None`` 表示清空。

    Args:
        fact_id: 目标 fact 的数据库主键。LLM 可能传字符串 / float / bool,
            走 :func:`_parse_fact_id` 统一 coerce 成 ``[1, 10**18]`` 区间内
            int; 不可解析值返回 ``ok=False`` 错误回执, 不写 DB。
        new_title: 新 title。必须 ``str`` (空串 / 含内容均可, 表示覆盖)
            或 ``None`` (literal None 表示清空)。走 :func:`_validate_title`
            统一校验; 非法类型 (int / list / dict / bool) 或超长 (>200 strip)
            返回 ``ok=False`` 错误回执, 不写 DB。

    Returns:
        ``dict[str, Any]``, LLM 工具契约字段 (成功 / 失败两种):
            * 成功路径:
                * ``ok`` (bool): True
                * ``id`` (int): 被更新的 fact_id (与 ``fact_id`` 入参一致)
                * ``title`` (str | None): 写入后的 title (即 ``new_title_eff``,
                  含"清空"语义)
            * 失败路径 (``fact_id`` 不可解析 / ``new_title`` 非法 / fact_id 不存在):
                * ``ok`` (bool): False
                * ``id`` (int | None): fact_id 不可解析时为 None, 其它失败时为 int
                * ``error`` (str): 简短错误描述 (供 LLM 复读给用户)
    """
    # fact_id 走 _parse_fact_id: 不可解析 (None / bool / 字符串"abc") → None
    fid_eff: int | None = _parse_fact_id(fact_id)
    if fid_eff is None:
        return {"ok": False, "id": None, "error": "fact_id 不可解析"}

    # new_title 走 _validate_title: 抛 ValueError 表示非法, 捕获后 wrap 成错误回执
    try:
        new_title_eff: str | None = _validate_title(new_title)
    except ValueError as exc:
        return {"ok": False, "id": fid_eff, "error": str(exc)}

    # 全部前置门通过, 落库; 不取回 Fact 快照, 保持原版 LLM 契约
    # (成功路径只回 ok / id / title, 不暴露完整 Fact 字段)。
    m = MemoryManager()
    fact = m.update_title(fact_id=fid_eff, new_title=new_title_eff)
    if fact is None:
        # fact_id 解析成功但底层 UPDATE 影响 0 行 (DB 里没这条 fact)
        return {"ok": False, "id": fid_eff, "error": "fact_id 不存在"}
    return {
        "ok": True,
        "id": fid_eff,
        "title": new_title_eff,
    }


__all__ = [
    "memory_save",
    "memory_recall",
    "memory_recall_range",
    "memory_top_frequent",
    "memory_recall_by_tag",
    "memory_recall_by_title",
    "memory_update_title",
]