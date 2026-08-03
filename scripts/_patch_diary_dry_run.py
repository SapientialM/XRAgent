"""One-shot patch v2: 给 diary_archive tool wrapper 加 dry_run 支持。

util/ 那边上一轮已 patch 完。本轮只动 tools/diary_tools.py。
策略：str.replace 锚点 + count==1 assert 守门。
"""
from pathlib import Path

ROOT = Path("src/xragent")
tool_path = ROOT / "tools" / "diary_tools.py"
tool_text = tool_path.read_text(encoding="utf-8")


def do(label: str, old: str, new: str) -> None:
    n = tool_text.count(old)
    assert n == 1, f"[{label}] 期望 anchor 唯一 (count==1), 实际 {n}"
    tool_text.replace(old, new, 1)
    # NOTE: do NOT actually replace yet — we'll write once at the end after
    # all assertions pass. But we need to track replacements in tool_text.
    # Simpler: just chain them in tool_text and write once.
    raise RuntimeError("use chained version below")


# Chained approach:
text = tool_text

# 2a. docstring
OLD_ARGS = (
    "            一律返回 ``ok=False``。\n"
    "\n"
    "    Returns:\n"
)
NEW_ARGS = (
    "            一律返回 ``ok=False``。\n"
    "        dry_run: ``True`` 时只列会被归档的周,不真合并 / 不删 daily 文件\n"
    "            (走 :func:`xragent.util.diary_archive.auto_archive` 的 dry_run\n"
    "            模式,与 ``snapshot_cleanup`` 的 dry_run 语义对齐 — LLM 想\n"
    "            看一眼会动哪些时不用真跑)。默认 ``False``。\n"
    "            非 ``bool`` (含 ``0/1`` 整数 / ``\"true\"`` 字符串) 一律返回\n"
    "            ``ok=False``, 与 :func:`_validate_int_field` 里排除 ``bool``\n"
    "            的方向对称 — 一边不许 ``True/False`` 当数字,这边不许 ``0/1``\n"
    "            当布尔 (避免 LLM 把 ``dry_run=0`` 当 ``False`` 用)。\n"
    "\n"
    "    Returns:\n"
)
n = text.count(OLD_ARGS)
assert n == 1, f"[tool docstring] count==1 fail, got {n}"
text = text.replace(OLD_ARGS, NEW_ARGS, 1)
print("  [ok] tool docstring 注入 dry_run 字段")

# 2b. function signature
OLD_SIG = "def diary_archive(weeks_threshold: int = 2) -> dict[str, Any]:\n"
NEW_SIG = (
    "def diary_archive(\n"
    "    weeks_threshold: int = 2,\n"
    "    dry_run: bool = False,\n"
    ") -> dict[str, Any]:\n"
)
n = text.count(OLD_SIG)
assert n == 1, f"[tool signature] count==1 fail, got {n}"
text = text.replace(OLD_SIG, NEW_SIG, 1)
print("  [ok] tool signature 加 dry_run kwarg")

# 2c. body: 校验 + 透传
OLD_CALL = (
    "        max_value=_WEEKS_THRESHOLD_MAX,\n"
    "    )\n"
    "    if err is not None:\n"
    "        return _fail(err)\n"
    "\n"
    "    s = get_settings()\n"
    "    try:\n"
    "        result = auto_archive(s.diary_dir, weeks_threshold)\n"
    "    except OSError as e:\n"
    "        return _fail(f\"归档失败: {type(e).__name__}: {e}\")\n"
    "    return result\n"
)
NEW_CALL = (
    "        max_value=_WEEKS_THRESHOLD_MAX,\n"
    "    )\n"
    "    if err is not None:\n"
    "        return _fail(err)\n"
    "\n"
    "    # dry_run 校验: bool 是 int 子类,严格 isinstance(value, bool) 才放行\n"
    "    # (LLM 偶尔传 0/1 当 False/True,语义滑移不挡掉日后会埋雷)。\n"
    "    if not isinstance(dry_run, bool):\n"
    "        return _fail(\n"
    "            f\"dry_run 必须是 bool，实际类型 {type(dry_run).__name__}\"\n"
    "        )\n"
    "\n"
    "    s = get_settings()\n"
    "    try:\n"
    "        result = auto_archive(s.diary_dir, weeks_threshold, dry_run=dry_run)\n"
    "    except OSError as e:\n"
    "        return _fail(f\"归档失败: {type(e).__name__}: {e}\")\n"
    "    return result\n"
)
n = text.count(OLD_CALL)
assert n == 1, f"[tool body] count==1 fail, got {n}"
text = text.replace(OLD_CALL, NEW_CALL, 1)
print("  [ok] tool body 注入 dry_run 校验 + 透传")

tool_path.write_text(text, encoding="utf-8")
print(f"  [ok] write {tool_path}")

# py_compile self-check
import py_compile
py_compile.compile(str(tool_path), doraise=True)
print(f"  [ok] py_compile {tool_path}")