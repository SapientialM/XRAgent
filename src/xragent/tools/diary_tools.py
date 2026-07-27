"""diary 写入。"""
from __future__ import annotations

import time

from ..config.settings import get_settings
from .blacklist import PathSandbox


def diary_write(title: str, body: str) -> dict:
    sb = PathSandbox.from_settings()
    s = get_settings()
    day = time.strftime("%Y-%m-%d")
    target = sb.assert_writable(s.diary_dir / f"{day}.md")
    ts = time.strftime("%H:%M:%S")
    block = f"\n## [{ts}] {title}\n\n{body.rstrip()}\n"
    with target.open("a", encoding="utf-8") as f:
        f.write(block)
    return {"ok": True, "path": target.relative_to(sb.root).as_posix()}
