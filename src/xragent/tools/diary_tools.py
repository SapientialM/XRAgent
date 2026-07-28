"""diary 写入。"""
from __future__ import annotations

import time

from ..config.settings import get_settings
from .blacklist import PathSandbox


def _require_nonblank(field: str, value: object) -> str | None:
    """非空白字符串校验：失败返回错误信息，成功返回 None。"""
    if not isinstance(value, str):
        return f"{field} 必须是字符串，实际类型 {type(value).__name__}"
    if not value.strip():
        return f"{field} 不能为空或纯空白"
    return None


def diary_write(title: str, body: str) -> dict:
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