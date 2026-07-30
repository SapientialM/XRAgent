"""filesystem 工具 (read / list / write)。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config.settings import get_settings
from .blacklist import BlacklistedTarget, PathSandbox


# -------------------- 公共 helper --------------------

def _fail(error: str) -> dict[str, Any]:
    """``ok=False`` 字典工厂,read_file / list_dir / write_file 三处共用。

    抽出来原因: 三个工具的"越界 / 不存在 / 类型错 / 权限错"失败路径
    之前各自 inline 写 ``{"ok": False, "error": ...}``,文案漂移风险大,
    现在统一收口。文案前缀 ("读取失败" / "写入失败" / "列出失败") 由
    调用方在传入 ``error`` 时决定, 方便 LLM 看到立刻定位出错环节。
    """
    return {"ok": False, "error": error}


# -------------------- 路径围栏 helpers --------------------

def _resolve_inside(path: str) -> tuple[Path | None, str | None]:
    """read_file / list_dir 共用的越界校验封装。

    调用方收到 ``(target, None)`` 继续走流程;
    收到 ``(None, error_str)`` 直接 ``_fail(error_str)`` 返回。

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
    """write_file 专用: 走 ``assert_writable`` (围栏 + 黑名单双层校验)。

    与 :func:`_resolve_inside` 形态对齐, 写入路径的拒因有 "越界" 和
    "黑名单命中" 两类, 错误文案由 PathSandbox / ``is_protected`` 决定,
    此处只透传。
    """
    try:
        target = PathSandbox.from_settings().assert_writable(path)
        return target, None
    except BlacklistedTarget as e:
        return None, str(e)


# -------------------- public tools --------------------

def read_file(path: str) -> dict[str, Any]:
    """读取仓库内文本文件。

    路径围栏由 ``PathSandbox.assert_inside`` 负责 (不查黑名单, 保留
    读取当前对 AGENTS.md/.env 等的现有契约——见 test_fs_tools 中
    ``test_read_file_currently_does_not_block_agents_md`` 锁定的快照)。

    失败路径统一返回 ``_fail(error)``:
      * 越界 → 由 PathSandbox 给文案
      * 不存在 / 是目录 / 非 utf-8 / **OSError** (PermissionError 等)
        → ``"读取失败: <type>: <msg>"``

    Returns:
        ``dict[str, Any]``, LLM 工具契约字段:
            * ``ok`` (bool): True 表示读取成功
            * 成功时附加 ``path`` / ``size`` / ``content`` (str / int / str)
            * 失败时附加 ``error`` (str): 含字段名 + 实际类型 / 错误类名
    """
    target, err = _resolve_inside(path)
    if err is not None:
        return _fail(err)
    assert target is not None  # narrow for type checker
    if not target.exists():
        return _fail(f"目标不存在: {path}")
    if target.is_dir():
        return _fail(f"目标是目录，不能 read: {path}")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _fail(f"非 utf-8 文件: {path}")
    except OSError as e:
        # PermissionError / IsADirectoryError (race) / 等落到这里。
        # 之前直接上抛会破坏 "工具始终返回 dict" 的承诺 (test_fs_tools_oserror.py 锁)。
        return _fail(f"读取失败: {type(e).__name__}: {e}")
    rel = target.relative_to(get_settings().repo_root).as_posix()
    return {"ok": True, "path": rel, "size": len(content), "content": content}


def list_dir(path: str = ".") -> dict[str, Any]:
    """列出仓库内目录条目, 自动过滤 ``.git/``。

    围栏校验同 :func:`read_file`, 统一走 ``_resolve_inside``, 避免两处
    try/except 重复——后续若要给读操作加黑名单, 只动 PathSandbox 即可。

    ``iterdir`` 与 ``stat`` 都包了 ``OSError`` 兜底, 单文件 stat 失败
    不影响其他条目 (size 退化到 0), 但目录级 iterdir 失败会整体返回
    ``ok=False``。文案前缀 ``"列出失败"`` 让 LLM 立刻定位出错环节。

    Returns:
        ``dict[str, Any]``, LLM 工具契约字段:
            * ``ok`` (bool): True 表示列出成功
            * 成功时附加 ``path`` (str) + ``entries`` (list[dict])
            * 失败时附加 ``error`` (str)
    """
    target, err = _resolve_inside(path)
    if err is not None:
        return _fail(err)
    assert target is not None
    if not target.is_dir():
        return _fail(f"不是目录: {path}")
    try:
        children = sorted(target.iterdir(), key=lambda p: p.name)
    except OSError as e:
        # 目录权限被收回 / 突然被卸载等。test_fs_tools.py 新增 case 锁此契约。
        return _fail(f"列出失败: {type(e).__name__}: {e}")
    repo_root: Path = get_settings().repo_root
    entries: list[dict[str, Any]] = []
    for child in children:
        if child.name == ".git":
            continue
        rel = child.relative_to(repo_root).as_posix()
        # 单文件 stat 失败不致命 (permission revoked 后立刻 list), 退化到 size=0
        try:
            is_dir = child.is_dir()
            size: int = child.stat().st_size if is_dir is False else 0
        except OSError:
            is_dir = False
            size = 0
        entries.append({"name": rel, "is_dir": is_dir, "size": size})
    return {"ok": True, "path": path, "entries": entries}


def write_file(path: str, content: str) -> dict[str, Any]:
    """创建或覆盖仓库内文件。HITL 审批在 registry 层 (``risk=high``)。

    ``mkdir`` 与 ``write_text`` 各包一层 ``OSError`` 兜底, 失败文案前缀
    ``"写入失败"`` 与 :func:`read_file` 的 ``"读取失败"`` 对齐, 便于
    LLM 看到日志直接定位 (test_fs_tools_oserror.py 锁定)。

    Returns:
        ``dict[str, Any]``, LLM 工具契约字段:
            * ``ok`` (bool): True 表示写入成功
            * 成功时附加 ``path`` / ``size`` (str / int)
            * 失败时附加 ``error`` (str): 含 ``"写入失败: <type>: <msg>"``
    """
    target, err = _resolve_writable(path)
    if err is not None:
        return _fail(err)
    assert target is not None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return _fail(f"写入失败: {type(e).__name__}: {e}")
    try:
        target.write_text(content, encoding="utf-8")
    except OSError as e:
        return _fail(f"写入失败: {type(e).__name__}: {e}")
    rel = target.relative_to(get_settings().repo_root).as_posix()
    return {"ok": True, "path": rel, "size": len(content)}