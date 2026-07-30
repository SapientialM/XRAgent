"""diary 写入。"""
from __future__ import annotations

import time
from typing import Any

from ..config.settings import get_settings
from .blacklist import PathSandbox


def _require_nonblank(field: str, value: object) -> str | None:
    """非空白字符串校验：失败返回错误信息，成功返回 None。

    Args:
        field: 字段名（用于错误信息中点名），例如 ``"title"`` / ``"body"``。
        value: 待校验的值；接受任意类型，非字符串或纯空白都会被拒。

    Returns:
        ``None`` 表示校验通过；否则返回描述性错误信息（已包含字段名 + 实际类型）。
    """
    if not isinstance(value, str):
        return f"{field} 必须是字符串，实际类型 {type(value).__name__}"
    if not value.strip():
        return f"{field} 不能为空或纯空白"
    return None


def diary_write(title: str, body: str) -> dict[str, Any]:
    """在当天 diary 文件中追加一段 ``## [HH:MM:SS] <title>`` 记录。

    写入前会做非空 / 纯空白校验，任何一项不通过都返回 ``ok=False`` 而
    不触碰目标文件（避免校验失败时仍创建空 diary 文件，污染当日记录）。

    Args:
        title: 章节标题；非空且非纯空白。允许中文 / emoji / markdown 字符（按字面写入）。
        body: 正文；非空且非纯空白。末尾的连续换行会被 ``rstrip`` 吃掉，避免块间出现多余空行。

    Returns:
        ``dict[str, Any]``，LLM 工具契约字段：
            * ``ok`` (bool): 校验 + 写入均成功为 True；任一字段校验失败为 False
            * 成功时附加 ``path`` (str): 写入文件相对 ``repo_root`` 的 POSIX 路径
              （如 ``"diary/2026-07-30.md"``），便于上层直接展示
            * 失败时附加 ``error`` (str): 描述性错误信息，已包含字段名 + 实际类型
    """
    for field, value in (("title", title), ("body", body)):
        err = _require_nonblank(field, value)
        if err is not None:
            return {"ok": False, "error": err}

    sb = PathSandbox.from_settings()
    s = get_settings()
    day = time.strftime("%Y-%m-%d")
    target = sb.assert_writable(s.diary_dir / f"{day}.md")
    ts = time.strftime("%H:%M:%S")
    block = f"\n## [{ts}] {title}\n\n{body.rstrip()}\n"
    with target.open("a", encoding="utf-8") as f:
        f.write(block)
    return {"ok": True, "path": target.relative_to(sb.root).as_posix()}
