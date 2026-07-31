"""filesystem 工具 (read / list / write)。"""
from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

from ..config.settings import get_settings
from .blacklist import BlacklistedTarget, PathSandbox


# -------------------- 默认上限常量 --------------------
# 模块级常量, 方便测试用 monkeypatch 调小来构造边界用例, 避免动辄 200KB+
# 字符串拖慢 pytest。sanity 范围 (test_tools_refactor 锁):
#   - 10_000  <= MAX_READ_BYTES <= 10_000_000   (10KB ~ 10MB)
#   - MAX_WRITE_BYTES >= MAX_READ_BYTES
#   - 10_000  <= MAX_WRITE_BYTES <= 100_000_000  (10KB ~ 100MB)
# 读比写更小: read 进 LLM context, write 只到磁盘; 给 write 更宽的预算
# 让 "Agent 一次写大块 README / schema" 类用例不至于被误拒。
MAX_READ_BYTES: int = 200_000     # 200KB
MAX_WRITE_BYTES: int = 1_000_000  # 1MB


# -------------------- 公共 helper --------------------

def _fail(error: str) -> dict[str, Any]:
    """``ok=False`` 字典工厂,read_file / list_dir / write_file 三处共用。

    抽出来原因: 三个工具的"越界 / 不存在 / 类型错 / 权限错"失败路径
    之前各自 inline 写 ``{"ok": False, "error": ...}``,文案漂移风险大,
    现在统一收口。文案前缀 ("读取失败" / "写入失败" / "列出失败") 由
    调用方在传入 ``error`` 时决定, 方便 LLM 看到立刻定位出错环节。
    """
    return {"ok": False, "error": error}


def _read_text_capped(path: Path, *, max_bytes: int | None) -> tuple[str, bool]:
    """读取 ``path`` 的 utf-8 文本, 必要时按字节截断。

    行为约定:
      * ``max_bytes`` 为 None / 非 int / bool / <= 0 → 当作无上限,
        保持旧 ``read_file`` 行为 (向后兼容 + 容忍 LLM 传错类型)。
        这一宽松策略对齐 ``exec_tools._resolve_timeout``, 避免一个
        类型错误就把整次 read 搞挂。
      * 文件 size <= max_bytes → 返回全文, ``truncated=False``.
      * 文件 size >  max_bytes → 只读前 ``max_bytes`` 字节, ``truncated=True``.
        用 binary 模式读取 + ``errors="replace"`` 解码, 防止恰好切在
        多字节字符边界时 UnicodeDecodeError 把工具搞崩 (``read_file``
        的契约是 "始终返回 dict", 所以宁可丢字符也别 raise)。

    Args:
        path: 已过围栏校验的仓库内 Path。
        max_bytes: 字节上限。语义见上。

    Returns:
        ``(text, truncated)``: ``text`` 是返回的字符串, ``truncated`` 表示
        文件是否被截断 (True 表示有字节没读到, 调用方应自行决定是否
        再翻页 / 换工具)。
    """
    if (
        max_bytes is None
        or not isinstance(max_bytes, int)
        or isinstance(max_bytes, bool)
        or max_bytes <= 0
    ):
        return path.read_text(encoding="utf-8"), False
    size = path.stat().st_size
    if size <= max_bytes:
        return path.read_text(encoding="utf-8"), False
    with path.open("rb") as f:
        raw = f.read(max_bytes)
    return raw.decode("utf-8", errors="replace"), True


# -------------------- 路径围栏 helpers --------------------

def _sandbox_resolve(
    path: str, *, writable: bool = False
) -> tuple[Path | None, dict[str, Any] | None]:
    """read_file / list_dir / write_file 共用的围栏 + 黑名单解析。

    与旧版 ``_resolve_inside`` / ``_resolve_writable`` 的差别:
      * 返回 ``(None, dict)`` 而非 ``(None, str)``: 直接给调用方一个
        ``ok=False`` 字典, 省一次 ``_fail(err_str)`` 包装, 减少类型漂移。
      * ``writable=False`` 走 ``assert_inside`` (只查围栏, 不查黑名单),
        与旧 ``read_file`` 行为一致 (test_fs_tools 锁).
      * ``writable=True`` 走 ``assert_writable`` (围栏 + 黑名单双层),
        ``AGENTS.md`` / ``.env`` 等受保护路径会被拒.

    调用方收到 ``(target, None)`` 继续走流程;
    收到 ``(None, err_dict)`` 直接 ``return err_dict``。
    """
    try:
        if writable:
            target = PathSandbox.from_settings().assert_writable(path)
        else:
            target = PathSandbox.from_settings().assert_inside(path)
        return target, None
    except BlacklistedTarget as e:
        return None, {"ok": False, "error": str(e)}


def _resolve_inside(path: str) -> tuple[Path | None, str | None]:
    """read_file / list_dir 共用的越界校验封装 (legacy 字符串返回形态)。

    新代码优先用 :func:`_sandbox_resolve`; 本函数保留是因为部分老
    调用方期望 ``(target, error_str)`` 二元组 (而非 dict), 拆掉会
    一次性破坏面太大。实现上转调 ``_sandbox_resolve`` 然后把
    ``err_dict["error"]`` 拆回 str —— 单行开销, 没有重复逻辑。
    """
    target, err_dict = _sandbox_resolve(path, writable=False)
    if err_dict is not None:
        return None, err_dict["error"]
    return target, None


def _resolve_writable(path: str) -> tuple[Path | None, str | None]:
    """write_file 专用: legacy 字符串返回形态, 内部转调 ``_sandbox_resolve``。

    与 :func:`_resolve_inside` 形态对齐, 写入路径的拒因有 "越界" 和
    "黑名单命中" 两类, 错误文案由 PathSandbox / ``is_protected`` 决定,
    此处只透传。
    """
    target, err_dict = _sandbox_resolve(path, writable=True)
    if err_dict is not None:
        return None, err_dict["error"]
    return target, None


# -------------------- public tools --------------------

def read_file(path: str, max_bytes: int | None = None) -> dict[str, Any]:
    """读取仓库内文本文件。

    路径围栏由 ``PathSandbox.assert_inside`` 负责 (不查黑名单, 保留
    读取当前对 AGENTS.md/.env 等的现有契约——见 test_fs_tools 中
    ``test_read_file_currently_does_not_block_agents_md`` 锁定的快照)。

    双层字节上限语义:
      * ``MAX_READ_BYTES`` (模块常量, 默认 200KB) —— 硬上限, 超过直接
        ``ok=False`` 拒绝, 防 Agent 误读超大文件撑爆内存 / 拖慢推理。
        失败时带 ``size`` / ``limit`` 字段, LLM 可据此决定是否改用
        ``exec_tools`` (head/tail) 或 ``list_dir``。
      * ``max_bytes`` (参数, 软上限) —— LLM 主动指定的截断点; 超过只
        截断不拒 (走 ``_read_text_capped``), ``truncated=True`` 标记。
        ``max_bytes`` 显式时 **优先于** ``MAX_READ_BYTES``: LLM 既然
        知道自己在读大文件 (e.g. max_bytes=1_000_000), 就不该再被
        200KB 默认值拦下。
      * ``max_bytes=None`` (默认) → 走 ``MAX_READ_BYTES`` 硬上限。

    v0.3 新增 ``original_size`` 字段: 始终报告文件在磁盘上的原始字节
    数 (``stat().st_size``), 即便 ``truncated=False`` 也带上。
    动机是让 LLM 单次 read 就能判断 "这个文件总共多大 / 我看到的是不是
    全部", 不用额外再走 ``list_dir`` + 算 size。多字节 UTF-8 下
    ``size`` 是返回的 *字符* 数, ``original_size`` 是 *字节* 数, 两个
    数字在非 ASCII 内容下会不一致——这是有意的 (size 对应 LLM 看到的
    文本长度, original_size 对应 max_bytes 操作的字节预算)。

    失败路径统一返回 ``_fail(error)`` 或带 size/limit 字段的 dict:
      * 越界 → 由 PathSandbox 给文案
      * 不存在 / 是目录 / 非 utf-8 / **OSError** (PermissionError 等)
        → ``"读取失败: <type>: <msg>"``
      * 超 ``MAX_READ_BYTES`` → ``{"ok": False, "error": "文件过大", "size": N, "limit": M}``

    Returns:
        ``dict[str, Any]``, LLM 工具契约字段:
            * ``ok`` (bool): True 表示读取成功
            * 成功时附加 ``path`` / ``size`` / ``original_size`` /
              ``content`` / ``truncated`` (str / int / int / str / bool):
              ``size`` 是返回内容字符数; ``original_size`` 是文件原始
              字节数; ``truncated`` 仅当 max_bytes 真生效且文件更长
              时为 True
            * 失败时附加 ``error`` (str): 含字段名 + 实际类型 / 错误类名;
              "文件过大" 分支还附 ``size`` / ``limit`` 两个 int。
    """
    target, err = _resolve_inside(path)
    if err is not None:
        return _fail(err)
    assert target is not None  # narrow for type checker
    if not target.exists():
        return _fail(f"目标不存在: {path}")
    if target.is_dir():
        return _fail(f"目标是目录，不能 read: {path}")
    # 硬上限 (max_bytes=None 才生效); max_bytes 显式时让 LLM 自决
    if max_bytes is None:
        size_on_disk = target.stat().st_size
        if size_on_disk > MAX_READ_BYTES:
            return {
                "ok": False,
                "error": "文件过大",
                "size": size_on_disk,
                "limit": MAX_READ_BYTES,
            }
    try:
        content, truncated = _read_text_capped(target, max_bytes=max_bytes)
    except UnicodeDecodeError:
        return _fail(f"非 utf-8 文件: {path}")
    except OSError as e:
        # PermissionError / IsADirectoryError (race) / 等落到这里。
        # 之前直接上抛会破坏 "工具始终返回 dict" 的承诺 (test_fs_tools_oserror.py 锁)。
        return _fail(f"读取失败: {type(e).__name__}: {e}")
    # 独立 stat 拿原始字节数; 截断路径下 _read_text_capped 内部已 stat 过一次,
    # 多花一次 stat (μs 级) 换来 read_file 公开契约里 original_size 字段稳定
    # 且 _read_text_capped 签名 2-tuple 不破——白盒测试 ``_read_text_capped`` 锁的就是 2-tuple。
    original_size = target.stat().st_size
    rel = target.relative_to(get_settings().repo_root).as_posix()
    return {
        "ok": True,
        "path": rel,
        "size": len(content),
        "original_size": original_size,
        "content": content,
        "truncated": truncated,
    }


def list_dir(path: str = ".") -> dict[str, Any]:
    """列出仓库内目录条目, 自动过滤 ``.git/``。

    围栏校验同 :func:`read_file`, 统一走 ``_resolve_inside``, 避免两处
    try/except 重复——后续若要给读操作加黑名单, 只动 PathSandbox 即可。

    ``iterdir`` 与 ``stat`` 都包了 ``OSError`` 兜底, 单文件 stat 失败
    不影响其他条目 (size 退化到 0), 但目录级 iterdir 失败会整体返回
    ``ok=False``。文案前缀 ``"列出失败"`` 让 LLM 立刻定位出错环节。

    性能细节: 每个子条目走 *单次* ``child.stat()`` 同时拿到 ``is_dir``
    与 ``size``, 比之前 ``child.is_dir()`` + ``child.stat()`` 各一次
    syscall 少一半 stat 调用 (大目录 / NFS / 容器 fs 下尤其明显);
    副作用是消除了 ``is_dir()`` 成功但紧跟的 ``stat()`` 失败这种竞态
    退化路径, OSError 兜底现在只在 *一次* 调用上发生。

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
        # 单次 stat 同时拿 is_dir / size: 避免 ``is_dir()`` + ``stat()`` 两轮 syscall,
        # 并消除 "is_dir 成功但 stat 失败" 的竞态退化路径。S_ISDIR 直接看 mode 位,
        # 与 ``Path.is_dir()`` 语义一致 (跟随 symlink)。
        try:
            st = child.stat()
            is_dir: bool = stat.S_ISDIR(st.st_mode)
            size: int = 0 if is_dir else st.st_size
        except OSError:
            is_dir = False
            size = 0
        entries.append({"name": rel, "is_dir": is_dir, "size": size})
    return {"ok": True, "path": path, "entries": entries}


def write_file(path: str, content: str) -> dict[str, Any]:
    """创建或覆盖仓库内文件。HITL 审批在 registry 层 (``risk=high``)。

    三层防护:
      1. **类型校验** —— ``content`` 必须是 ``str``; 非字符串 (e.g. ``int`` /
         ``None`` / ``dict``) 直接 ``ok=False`` 拒绝, 文案带 ``type(content).__name__``
         让 LLM 看到立刻知道传错类型。旧版会传给 ``Path.write_text`` 然后
         抛 ``AttributeError``, 经黑名单转 ``ok=False`` 但文案对 LLM 不友好。
      2. **大小上限** —— ``len(content) > MAX_WRITE_BYTES`` 直接拒,
         带 ``size`` / ``limit`` 字段, 防止 Agent 一次写出超大文件 (OOM /
         写满磁盘 / 拖慢 git push)。
      3. **OSError 兜底** —— ``mkdir`` 与 ``write_text`` 各包一层
         ``OSError``, 失败文案前缀 ``"写入失败"`` 与 :func:`read_file` 的
         ``"读取失败"`` 对齐, 便于 LLM 看到日志直接定位
         (test_fs_tools_oserror.py 锁定)。

    Returns:
        ``dict[str, Any]``, LLM 工具契约字段:
            * ``ok`` (bool): True 表示写入成功
            * 成功时附加 ``path`` / ``size`` (str / int)
            * 失败时附加 ``error`` (str); 类型错 / 过大分支还附
              ``type`` / ``size`` / ``limit`` 等诊断字段
    """
    target, err = _resolve_writable(path)
    if err is not None:
        return _fail(err)
    assert target is not None
    # 类型校验先于一切: 避免把 int/None 传给 write_text 抛 AttributeError
    if not isinstance(content, str):
        return {
            "ok": False,
            "error": f"content 必须是字符串, got {type(content).__name__}",
            "type": type(content).__name__,
        }
    # 大小上限 (按字符数, 与 len(content) 一致; utf-8 多字节下字节数更大,
    # 但 LLM 看的是字符, 用 len 对齐更直观)。
    if len(content) > MAX_WRITE_BYTES:
        return {
            "ok": False,
            "error": "写入内容过大",
            "size": len(content),
            "limit": MAX_WRITE_BYTES,
        }
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