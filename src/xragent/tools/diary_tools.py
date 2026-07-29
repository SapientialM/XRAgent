"""diary 写入。"""
from __future__ import annotations

import time

from ..config.settings import get_settings
from .blacklist import PathSandbox


def _require_nonblank(field: str, value: object) -> str | None:
    """校验给定字段是否为非空白字符串。

    用于 diary_write 工具在写入前的输入合法性检查；任一字段不通过时，
    工具直接返回 ``{"ok": False, "error": err}`` 而不触达文件系统。

    Args:
        field: 字段名（如 ``"title"``、``"body"``），仅用于构造可读错误信息。
        value: 待校验的值；期望是 ``str``，其它类型也算非法。

    Returns:
        ``None`` 表示校验通过；否则返回中文化的错误描述字符串，供调用方
        直接放进工具返回的 ``error`` 字段。
    """
    if not isinstance(value, str):
        return f"{field} 必须是字符串，实际类型 {type(value).__name__}"
    if not value.strip():
        return f"{field} 不能为空或纯空白"
    return None


def diary_write(title: str, body: str) -> dict:
    """把一条 diary 条目追加到当天文件（``diary/YYYY-MM-DD.md``）。

    行为细节：
      * 目标路径走 ``PathSandbox.assert_writable``，越界写入会被 blacklist
        拒绝（保证 ``diary/turns/``、``.env`` 等禁区不被污染）。
      * 父目录缺失时由 ``PathSandbox`` 内部处理；本函数不直接 ``mkdir``。
      * 追加格式：``\\n## [HH:MM:SS] {title}\\n\\n{body.rstrip()}\\n``，
        每次条目之间天然带一个空行，便于 Markdown 渲染。

    Args:
        title: 条目标题；会出现在 ``## [ts] {title}`` 行首。
        body: 条目正文；末尾空白会被 ``rstrip`` 截掉，但内部换行保留。

    Returns:
        成功时 ``{"ok": True, "path": "<相对于 sandbox root 的 POSIX 路径>"}``；
        校验失败时 ``{"ok": False, "error": "<中文错误描述>"}``。
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