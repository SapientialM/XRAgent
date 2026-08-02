"""diary 写入 / 归档工具。

历史
----
2026-07-30 round：``diary_write`` 之前没有 OSError 兜底，遇到 PermissionError /
磁盘满时会直接向上抛 OSError，破坏 LLM 工具层 "always returns dict" 的契约
（``fs_tools`` 已经统一改造过，本次把 ``diary_tools`` 也对齐）。同时把
``## [HH:MM:SS] title\\n\\nbody\\\\n`` 块格式抽成 ``_format_block`` helper，
方便后续 ``diary_archive`` / 别的写日记入口复用同一种格式。

2026-08-03 round：补 ``diary_archive`` 薄包装。``util/diary_archive.py`` 已经
提供 ``auto_archive(diary_dir, weeks_threshold)`` 核心逻辑，但 LLM 工具层
一直没有 thin wrapper — 调用方写 ``diary_tools.diary_archive(...)`` 会
AttributeError，于是 ``tests/test_diary_archive_behavior.py`` 整体被跳过。
本次 wrapper 显式走 ``settings.diary_dir``（不接受外部路径参数），目的:
1. 路径源唯一,跟 ``diary_write`` 对齐
2. OSError 兜底保持工具层契约

2026-08-04 round：抽 ``_validate_int_field`` helper, ``diary_archive`` 的
``weeks_threshold`` 校验从内联 isinstance 三连收敛到一处, 同时补
``max_value`` 上限 clamp 防 LLM 误传 ``999999`` 让语义奇怪的请求过线。
错误信息格式与 ``_require_nonblank`` 对齐 (含字段名 + 实际类型/值)。
"""
from __future__ import annotations

import time
from typing import Any

from ..config.settings import get_settings
from ..util.diary_archive import auto_archive
from .blacklist import PathSandbox


# weeks_threshold 的上界: 520 周 ≈ 10 年 ISO 周, 覆盖任何合理的"长期保留"
# 意图, 同时挡掉 LLM 误传天文数字 (999999 这类请求落到 auto_archive 里
# 会变成 "10 年以内不归档", 语义奇怪且无审计价值)。与 exec_tools.MAX_TIMEOUT_S
# 600 的设计动机一致 — 给 LLM 工具参数一个"超出即报错"的硬上界。
_WEEKS_THRESHOLD_MAX: int = 520


def _fail(error: str) -> dict[str, Any]:
    """``ok=False`` 字典工厂；与 ``fs_tools._fail`` 同形 (LLM 工具层契约对齐)。"""
    return {"ok": False, "error": error}


def _require_nonblank(field: str, value: object) -> str | None:
    """非空白字符串校验。

    Args:
        field: 字段名 (用于错误信息中点名), 例如 ``"title"`` / ``"body"``。
        value: 待校验的值; 接受任意类型, 非字符串或纯空白都会被拒。

    Returns:
        ``None`` 表示校验通过; 否则返回描述性错误信息 (已包含字段名 +
        实际类型名), 调用方直接放进 ``_fail(...)``.
    """
    if not isinstance(value, str):
        return f"{field} 必须是字符串，实际类型 {type(value).__name__}"
    if not value.strip():
        return f"{field} 不能为空或纯空白"
    return None


def _validate_int_field(
    field: str,
    value: Any,
    *,
    min_value: int = 0,
    max_value: int | None = None,
) -> str | None:
    """整数范围校验: 失败返回错误信息, 通过返回 ``None``。

    抽出原因: ``diary_archive`` 的 ``weeks_threshold`` 之前是手写
    ``isinstance`` 链 + 负数判断两段, 与 :func:`_require_nonblank` 的
    "字段名 + 实际类型" 错误风格也不一致。收敛到一处后, 错误信息格式
    与 ``_require_nonblank`` 对齐 (含字段名 + 实际类型/值), 后续
    ``fs_tools`` / ``memory_tools`` 等加整型参数的工具都可以直接复用。

    Args:
        field: 字段名 (用于错误信息中点名)。
        value: 待校验值; LLM 工具参数为 ``Any``, 故这里也接受 ``Any``。
        min_value: 下界 (含); 传入值 < min_value 一律拒, 防止负数 / 0
            这类语义不合法值。
        max_value: 上界 (含); ``None`` 表示无上限。LLM 偶尔会脑抽传
            ``999999``, 不夹紧会让语义奇怪的请求过线 → 兜底拒绝。

    Returns:
        ``None`` 表示校验通过; 否则返回描述性错误信息 (已包含字段名 +
        实际类型名 / 越界值), 调用方直接放进 :func:`_fail`。
    """
    # bool 是 int 的子类, ``isinstance(True, int) is True``; 但 LLM 传
    # ``True`` 当数字几乎总是 bug, 单独排除。顺序必须先 bool 再 int,
    # 否则 ``not isinstance(value, int)`` 拦不下 True/False。
    if isinstance(value, bool) or not isinstance(value, int):
        return f"{field} 必须是整数，实际类型 {type(value).__name__}"
    if value < min_value:
        return f"{field} 不能小于 {min_value}，实际 {value}"
    if max_value is not None and value > max_value:
        return f"{field} 不能大于 {max_value}，实际 {value}"
    return None


def _format_block(ts: str, title: str, body: str) -> str:
    """组装 ``\\n## [ts] title\\n\\nbody\\n`` 块。

    抽出原因: diary_write 与未来的 re-archive 工具都要拼同一种块头格式,
    把格式漂移集中到一处, 跨天阅读时不会出现 "昨天是 ``## [ts] title``,
    今天变成 ``## ts - title``" 这种割裂。body 末尾 ``rstrip`` 也统一
    在此完成, 调用方传入任意尾部空白都安全 (避免块间出现连续 3+ 空行)。
    """
    return f"\n## [{ts}] {title}\n\n{body.rstrip()}\n"


def diary_write(title: str, body: str) -> dict[str, Any]:
    """在当天 diary 文件中追加一段 ``## [HH:MM:SS] <title>`` 记录。

    写入前做非空 / 纯空白校验，任何一项不通过都返回 ``ok=False`` 而不触
    碰目标文件（避免校验失败时仍创建空 diary 文件，污染当日记录）。
    OSError (PermissionError / 磁盘满 / 文件被占) 也会被转成 ``ok=False``
    而非上抛，遵循 LLM 工具调用层 "始终返回 dict" 的契约。

    Args:
        title: 章节标题; 非空且非纯空白。允许中文 / emoji / markdown 字符
            (按字面写入)。
        body: 正文; 非空且非纯空白。末尾的连续换行会被 ``rstrip`` 吃掉。

    Returns:
        ``dict[str, Any]``，LLM 工具契约字段:
            * ``ok`` (bool): 校验 + 写入均成功为 True; 任一字段校验失败 / OSError 为 False
            * 成功时附加 ``path`` (str): 写入文件相对 ``repo_root`` 的 POSIX
              路径 (如 ``"diary/2026-07-30.md"``)
            * 失败时附加 ``error`` (str): 描述性错误信息, 校验失败时含字段
              名 + 实际类型, OSError 时含 ``"写入失败: <type>: <msg>"``
    """
    for field, value in (("title", title), ("body", body)):
        err = _require_nonblank(field, value)
        if err is not None:
            return _fail(err)

    sb = PathSandbox.from_settings()
    s = get_settings()
    day = time.strftime("%Y-%m-%d")
    target = sb.assert_writable(s.diary_dir / f"{day}.md")
    ts = time.strftime("%H:%M:%S")
    block = _format_block(ts, title, body)
    try:
        with target.open("a", encoding="utf-8") as f:
            f.write(block)
    except OSError as e:
        return _fail(f"写入失败: {type(e).__name__}: {e}")
    rel_path: str = target.relative_to(sb.root).as_posix()
    return {"ok": True, "path": rel_path}


def diary_archive(weeks_threshold: int = 2) -> dict[str, Any]:
    """按 ISO 周归档超出阈值的 diary 每日文件。

    薄包装: 委托给 :func:`xragent.util.diary_archive.auto_archive`,
    日记目录路径固定走 :attr:`Settings.diary_dir`,不接受外部路径参数 —
    这样跟 :func:`diary_write` 一样,日记目录只有一个真相源,避免 LLM 工具
    层出现 ``"今天写 diary/ 而明天归档 archive/ "`` 这种路径漂移。

    ``weeks_threshold`` 校验走 :func:`_validate_int_field` helper: 非整数
    (含 bool) / 负数 / 超过 :data:`_WEEKS_THRESHOLD_MAX` 周 (10 年) 都会被
    兜底为 ``ok=False``,错误信息含字段名 + 实际类型/值,与 ``diary_write``
    校验风格对齐。

    Args:
        weeks_threshold: 阈值 (周), 默认 2 — mtime 落在 2 周以前的周会被
            合并到 ``diary/archive/{iso_year}-W{iso_week}.md`` 并删除
            原 daily 文件; 阈值内的周原封不动。允许 ``0`` (语义: 当周立刻
            归档)。负数 / 非整数 / 超过 :data:`_WEEKS_THRESHOLD_MAX` 周
            一律返回 ``ok=False``。

    Returns:
        ``dict[str, Any]``, LLM 工具契约字段:
            * ``ok`` (bool): 校验 + 委托均成功为 True; 校验失败 / OSError 为 False
            * 成功时透传 :func:`auto_archive` 的 ``archived`` /
              ``skipped`` 字段 (每个元素含 ``file`` / ``reason`` /
              ``iso_year`` / ``iso_week``)
            * 失败时附加 ``error`` (str): 描述性错误信息, 校验失败时含字段
              名 + 实际类型/值, OSError 时含 ``"归档失败: <type>: <msg>"``
    """
    # 走 _validate_int_field: 错误信息与 diary_write 的 _require_nonblank
    # 风格对齐 ("字段名 + 实际类型/值"), 后续 fs/memory 加整型参数的工具
    # 可直接复用同一 helper。max_value 兜底防止 LLM 误传 999999 这类
    # 天文数字 (语义上等价于 "10 年以内不归档", 审计价值低)。
    err: str | None = _validate_int_field(
        "weeks_threshold",
        weeks_threshold,
        min_value=0,
        max_value=_WEEKS_THRESHOLD_MAX,
    )
    if err is not None:
        return _fail(err)

    s = get_settings()
    try:
        result = auto_archive(s.diary_dir, weeks_threshold)
    except OSError as e:
        return _fail(f"归档失败: {type(e).__name__}: {e}")
    return result