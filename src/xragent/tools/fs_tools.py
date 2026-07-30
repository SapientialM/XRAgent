"""文件系统读 / 列目录工具。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config.settings import get_settings
from .blacklist import BlacklistedTarget, PathSandbox


def _resolve_inside(path: str) -> tuple[Path | None, str | None]:
    """read_file / list_dir 共用的越界校验封装。

    调用方收到 (target, None) 继续走流程;
    收到 (None, error_str) 直接 ``{"ok": False, "error": ...}`` 返回。

    抽出来之后:
      * 围栏策略改动只需动 PathSandbox 一个地方
      * 错误文案逐字保留 (test_fs_tools.py 的 ``"目标越界"`` 断言锁的就是该文案)
    """
    try:
        target = PathSandbox.from_settings().assert_inside(path)
        return target, None
    except BlacklistedTarget as e:
        return None, str(e)


def _resolve_writable(path: str) -> tuple[Path | None, str | None]:
    """write_file 专用: 走 assert_writable (围栏 + 黑名单双层校验)。

    与 _resolve_inside 形态对齐, 写入路径的拒因有"越界"和"黑名单命中"
    两类, 错误文案由 PathSandbox / is_protected 决定, 此处只透传。
    """
    try:
        target = PathSandbox.from_settings().assert_writable(path)
        return target, None
    except BlacklistedTarget as e:
        return None, str(e)


def read_file(path: str) -> dict[str, Any]:
    """读取仓库内文本文件。

    路径围栏由 PathSandbox.assert_inside 负责（不查黑名单，保留
    读取当前对 AGENTS.md/.env 等的现有契约——见 test_fs_tools 中
    test_read_file_currently_does_not_block_agents_md 锁定的快照）。
    """
    target, err = _resolve_inside(path)
    if err is not None:
        return {"ok": False, "error": err}
    assert target is not None  # narrow for type checker
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


def list_dir(path: str = ".") -> dict[str, Any]:
    """列出仓库内目录条目，自动过滤 .git/。

    围栏校验同 read_file, 统一走 _resolve_inside, 避免两处
    try/except 重复——后续若要给读操作加黑名单, 只动 PathSandbox 即可。
    """
    target, err = _resolve_inside(path)
    if err is not None:
        return {"ok": False, "error": err}
    assert target is not None
    if not target.is_dir():
        return {"ok": False, "error": f"不是目录: {path}"}
    repo_root = get_settings().repo_root
    entries: list[dict[str, Any]] = []
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


def write_file(path: str, content: str) -> dict[str, Any]:
    """创建或覆盖仓库内文件。HITL 审批在 registry 层（risk=high）。"""
    target, err = _resolve_writable(path)
    if err is not None:
        return {"ok": False, "error": err}
    assert target is not None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    rel = target.relative_to(get_settings().repo_root).as_posix()
    return {"ok": True, "path": rel, "size": len(content)}
