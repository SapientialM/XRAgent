"""One-shot patch for fs_tools.py: add offset_bytes to read_file.

锚点替换:
  P1: import 区追加 ``from .exec_tools import _coerce_int``
  P2: 文档字符串头块(``\"\"\"filesystem 工具 (read / list / write)。\"\"\"``) 后追加 intro 段
  P3: _read_text_capped 函数签名 + docstring + body 后, 追加 _read_text_window helper
  P4: read_file def 一行 + body 内 _read_text_capped 替换 + 新增 offset 校验段

每次 str.replace assert count==1, 失败即 raise, 不会有半成品写入。
"""
from __future__ import annotations
from pathlib import Path

FILE = Path("src/xragent/tools/fs_tools.py")
src = FILE.read_text(encoding="utf-8")

# ---- P1: add import ----
P1_OLD = "from .blacklist import BlacklistedTarget, PathSandbox\n"
P1_NEW = (
    "from .blacklist import BlacklistedTarget, PathSandbox\n"
    "from .exec_tools import _coerce_int  # 复用统一 int coerce (offset_bytes 兜底)\n"
)
assert src.count(P1_OLD) == 1, f"P1 anchor not unique: count={src.count(P1_OLD)}"
src = src.replace(P1_OLD, P1_NEW, 1)

# ---- P2: no module docstring change (keep tight) ----

# ---- P3: insert _read_text_window after _read_text_capped ----
# 锚点: _read_text_capped 函数体的最后一行 (return raw.decode ...) 后,
#       _io_fail 之前。我们用 _io_fail 的 def 行作为"插入位置之前"的锚点。
P3_ANCHOR_OLD = "def _io_fail(prefix: str, exc: OSError) -> dict[str, Any]:\n"
P3_NEW = (
    "def _read_text_window(\n"
    "    path: Path,\n"
    "    *,\n"
    "    offset_bytes: int | None = 0,\n"
    "    max_bytes: int | None = None,\n"
    ") -> tuple[str, bool, int]:\n"
    "    \"\"\"读 ``path``, 从 ``offset_bytes`` 起最多 ``max_bytes`` 字节。\n"
    "\n"
    "    抽取 :func:`_read_text_capped` 之外的\"字节窗口\"语义, 让\n"
    "    :func:`read_file` 能 offset+cap 组合而非仅从头 cap。新增\n"
    "    ``offset_bytes`` 是为了 LLM 翻页 —— 旧版 ``read_file`` 只能从\n"
    "    文件头读, 想看后半段得自己 ``grep -A`` 或重 ``write_file``,\n"
    "    工具调用层浪费一轮。\n"
    "\n"
    "    ``offset_bytes`` 与 ``max_bytes`` 各自走 :func:`_coerce_int`\n"
    "    统一兜底: 非 int / bool / 负数 → fallback 到 ``default``; 与\n"
    "    ``_read_text_capped`` 对 ``max_bytes`` 的宽松语义保持一致。\n"
    "\n"
    "    Args:\n"
    "        path: 已过围栏校验的仓库内 Path。\n"
    "        offset_bytes: 跳过前 N 字节; ``None`` / 非 int / bool /\n"
    "            负数 → fallback 0 (向后兼容)。offset > file_size 抛\n"
    "            :class:`ValueError` —— 这是调用方 bug, LLM 工具层应\n"
    "            转 ``ok=False`` 而不是默默截断, 让 LLM 自纠正。\n"
    "        max_bytes: 字节上限 (从 offset 起算); ``None`` → 无上限\n"
    "            (即 ``_read_text_capped`` 的旧行为)。\n"
    "\n"
    "    Returns:\n"
    "        ``(text, truncated, returned_byte_count)``:\n"
    "          * ``text`` (str): 返回的 utf-8 文本 (errors=\"replace\")\n"
    "          * ``truncated`` (bool): 文件从 offset 起是否被 max_bytes 截断\n"
    "          * ``returned_byte_count`` (int): 实际读取的字节数 (offset\n"
    "            之后; 不含跳过的部分)。LLM 拿到后能算 \"看看到第几个字节\"。\n"
    "\n"
    "    Raises:\n"
    "        ValueError: ``offset_bytes`` 归一化后 > 文件大小; 调用方需包\n"
    "            try/except 转 ``ok=False`` 错误回执。\n"
    "    \"\"\"\n"
    "    size = path.stat().st_size\n"
    "    offset_eff: int = _coerce_int(\n"
    "        offset_bytes, default=0, min_value=0, max_value=size\n"
    "    )\n"
    "    if offset_eff > size:\n"
    "        # 单独抛 ValueError 而非 fallback 到 0 —— \"跳过字节比文件\n"
    "        " "还长\"几乎总是调用方 bug, 让 LLM 看到 ok=False 文案自纠正\n"
    "        # 比起\"默默从偏移=文件末尾返回空串\"对调试更友好。\n"
    "        raise ValueError(\n"
    "            f\"offset_bytes ({offset_eff}) 超过文件大小 ({size})\"\n"
    "        )\n"
    "    # 计算剩余预算给 _read_text_capped: offset 后剩余 = size - offset_eff;\n"
    "    # max_bytes=None → 走\"无上限\"旧语义 (None). 显式传正整数 → 上限=min(max_bytes, remaining).\n"
    "    remaining: int = size - offset_eff\n"
    "    eff_max: int | None = (\n"
    "        None if max_bytes is None else min(\n"
    "            _coerce_int(max_bytes, default=remaining, min_value=0),\n"
    "            remaining,\n"
    "        )\n"
    "    )\n"
    "    # 偏移物理上用二进制 prefix read (头 offset_eff 字节扔掉),\n"
    "    # 比 seek + re-open 简单且对一次性 read 性能等价 (sub-MB 文件占比 99%)。\n"
    "    with path.open(\"rb\") as f:\n"
    "        if offset_eff:\n"
    "            f.read(offset_eff)\n"
    "        raw: bytes = f.read(eff_max) if eff_max is not None else f.read()\n"
    "    text: str = raw.decode(\"utf-8\", errors=\"replace\")\n"
    "    truncated: bool = eff_max is not None and len(raw) >= remaining and raw != b\"\"\n"
    "    return text, truncated, len(raw)\n"
    "\n"
    "\n"
    "def _io_fail(prefix: str, exc: OSError) -> dict[str, Any]:\n"
)
assert src.count(P3_ANCHOR_OLD) == 1, f"P3 anchor not unique: count={src.count(P3_ANCHOR_OLD)}"
src = src.replace(P3_ANCHOR_OLD, P3_NEW, 1)

# ---- P4a: read_file signature 加 offset_bytes 参数 ----
P4A_OLD = "def read_file(path: str, max_bytes: int | None = None) -> dict[str, Any]:\n"
P4A_NEW = (
    "def read_file(\n"
    "    path: str,\n"
    "    max_bytes: int | None = None,\n"
    "    *,\n"
    "    offset_bytes: int | None = 0,\n"
    ") -> dict[str, Any]:\n"
)
assert src.count(P4A_OLD) == 1, f"P4a anchor not unique: count={src.count(P4A_OLD)}"
src = src.replace(P4A_OLD, P4A_NEW, 1)

# ---- P4b: read_file 内的硬上限分支需要先抢 offset 余量 ----
# 之前对 max_bytes=None 时硬卡 file_size > MAX_READ_BYTES;
# 现在引入 offset 后, 硬上限应当看 "offset 后剩余字节" 是否超 MAX_READ_BYTES.
P4B_OLD = (
    "    if max_bytes is None:\n"
    "        size_on_disk = target.stat().st_size\n"
    "        if size_on_disk > MAX_READ_BYTES:\n"
    "            return {\n"
    "                \"ok\": False,\n"
    "                \"error\": \"文件过大\",\n"
    "                \"size\": size_on_disk,\n"
    "                \"limit\": MAX_READ_BYTES,\n"
    "            }\n"
)
P4B_NEW = (
    "    # offset 兜底: 非 int / bool / 负数 → fallback 0, 与 _read_text_capped 风格对齐.\n"
    "    # max_value 不在这里给, 给下面的硬上限分支一起算 \"offset 后剩余 vs MAX_READ_BYTES\".\n"
    "    offset_eff: int = _coerce_int(offset_bytes, default=0, min_value=0)\n"
    "    if max_bytes is None:\n"
    "        size_on_disk = target.stat().st_size\n"
    "        if offset_eff > size_on_disk:\n"
    "            return {\n"
    "                \"ok\": False,\n"
    "                \"error\": \"offset_bytes 超过文件大小\",\n"
    "                \"offset\": offset_eff,\n"
    "                \"size\": size_on_disk,\n"
    "            }\n"
    "        remaining_after_offset: int = size_on_disk - offset_eff\n"
    "        if remaining_after_offset > MAX_READ_BYTES:\n"
    "            return {\n"
    "                \"ok\": False,\n"
    "                \"error\": \"文件过大\",\n"
    "                \"size\": size_on_disk,\n"
    "                \"offset\": offset_eff,\n"
    "                \"limit\": MAX_READ_BYTES,\n"
    "            }\n"
)
assert src.count(P4B_OLD) == 1, f"P4b anchor not unique: count={src.count(P4B_OLD)}"
src = src.replace(P4B_OLD, P4B_NEW, 1)

# ---- P4c: read_file 把 _read_text_capped 调用换成 _read_text_window ----
P4C_OLD = (
    "        content, truncated = _read_text_capped(target, max_bytes=max_bytes)\n"
)
P4C_NEW = (
    "        try:\n"
    "            content, truncated, _ = _read_text_window(\n"
    "                target, offset_bytes=offset_eff, max_bytes=max_bytes\n"
    "            )\n"
    "        except ValueError as e:\n"
    "            # offset > file_size: 走 \"offset_bytes 超过文件大小\" 分支同样关键错误路径.\n"
    "            # _read_text_window 已在 offset>size 时抛, _coerce_int 兜底保护不了这一行.\n"
    "            size_now = target.stat().st_size\n"
    "            return {\n"
    "                \"ok\": False,\n"
    "                \"error\": f\"{e}\",\n"
    "                \"offset\": offset_eff,\n"
    "                \"size\": size_now,\n"
    "            }\n"
)
assert src.count(P4C_OLD) == 1, f"P4c anchor not unique: count={src.count(P4C_OLD)}"
src = src.replace(P4C_OLD, P4C_NEW, 1)

FILE.write_text(src, encoding="utf-8")
print(f"PATCHED {FILE} ({len(src)} bytes)")
