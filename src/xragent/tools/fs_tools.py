"""文件读写工具。"""
from __future__ import annotations

from pathlib import Path

from ..config.settings import get_settings
from .blacklist import PathSandbox


def read_file(path: str) -> dict:
    sb = PathSandbox.from_settings()
    target = sb.resolve(path)
    try:
        target.relative_to(sb.root)
    except ValueError as e:
        return {"ok": False, "error": f"目标越界: {target}"}
    if not target.exists():
        return {"ok": False, "error": f"不存在: {target}"}
    if target.is_dir():
        return {"ok": False, "error": f"是目录: {target}"}
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "error": "非 UTF-8 文件"}
    rel = target.relative_to(sb.root).as_posix()
    return {"ok": True, "path": rel, "size": len(content), "content": content}


def list_dir(path: str = ".") -> dict:
    sb = PathSandbox.from_settings()
    target = sb.resolve(path)
    try:
        target.relative_to(sb.root)
    except ValueError as e:
        return {"ok": False, "error": f"目标越界: {target}"}
    if not target.is_dir():
        return {"ok": False, "error": f"不是目录: {target}"}
    entries = []
    for child in sorted(target.iterdir()):
        if child.name == ".git":
            continue
        try:
            rel = child.relative_to(sb.root).as_posix()
        except ValueError:
            continue
        entries.append({"name": rel, "is_dir": child.is_dir(), "size": child.stat().st_size if child.is_file() else 0})
    return {"ok": True, "path": target.relative_to(sb.root).as_posix(), "entries": entries}


def write_file(path: str, content: str) -> dict:
    sb = PathSandbox.from_settings()
    target = sb.assert_writable(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    rel = target.relative_to(sb.root).as_posix()
    return {"ok": True, "path": rel, "size": len(content)}
