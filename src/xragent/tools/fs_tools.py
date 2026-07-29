"""文件系统读 / 列目录工具。"""
from __future__ import annotations

from ..config.settings import get_settings
from .blacklist import BlacklistedTarget, PathSandbox


def read_file(path: str) -> dict:
    """读取仓库内文本文件。

    路径围栏由 PathSandbox.assert_inside 负责（不查黑名单，保留
    读取当前对 AGENTS.md/.env 等的现有契约——见 test_fs_tools 中
    test_read_file_currently_does_not_block_agents_md 锁定的快照）。
    """
    try:
        target = PathSandbox.from_settings().assert_inside(path)
    except BlacklistedTarget as e:
        return {"ok": False, "error": str(e)}
    if not target.exists():
        return {"ok": False, "error": f"目标不存在: {path}"}
    if target.is_dir():
        return {"ok": False, "error": f"目标是目录，不能 read: {path}"}
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "error": f"非 utf-8 文件: {path}"}
    rel = target.relative_to(get_settings().repo_root).as_posix()
    return {"ok": True, "path": rel, "size": len(content), "content": content}


def list_dir(path: str = ".") -> dict:
    """列出仓库内目录条目，自动过滤 .git/。

    围栏校验同 read_file，统一走 assert_inside，避免两处 try/except
    重复——后续若要给读操作加黑名单，只动 PathSandbox 即可。
    """
    try:
        target = PathSandbox.from_settings().assert_inside(path)
    except BlacklistedTarget as e:
        return {"ok": False, "error": str(e)}
    if not target.is_dir():
        return {"ok": False, "error": f"不是目录: {path}"}
    repo_root = get_settings().repo_root
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: p.name):
        if child.name == ".git":
            continue
        rel = child.relative_to(repo_root).as_posix()
        entries.append(
            {
                "name": rel,
                "is_dir": child.is_dir(),
                "size": child.stat().st_size if child.is_file() else 0,
            }
        )
    return {"ok": True, "path": path, "entries": entries}


def write_file(path: str, content: str) -> dict:
    """创建或覆盖仓库内文件。HITL 审批在 registry 层（risk=high）。"""
    try:
        target = PathSandbox.from_settings().assert_writable(path)
    except BlacklistedTarget as e:
        return {"ok": False, "error": str(e)}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    rel = target.relative_to(get_settings().repo_root).as_posix()
    return {"ok": True, "path": rel, "size": len(content)}