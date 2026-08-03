
#!/usr/bin/env python3
"""一次性 5 处 patch evolve_tools.py — str.replace 锚点替换, 失败抛异常。"""
from pathlib import Path
import re

p = Path("src/xragent/tools/evolve_tools.py")
src = p.read_text(encoding="utf-8")
orig = src

# ---------- 1. imports ----------
old_imp = "import json
import os
import sys  # noqa: F401  — 对外保持可见, 防老人代码路径围栏用
"
assert old_imp in src, "imports anchor not found"
new_imp = (
    "import json
import os
import sys
"
    "from concurrent.futures import (
"
    "    ThreadPoolExecutor,
"
    "    TimeoutError as FuturesTimeoutError,
"
    "    as_completed,
"
    ")
"
)
src = src.replace(old_imp, new_imp, 1)

# ---------- 2. 常量 + _compile_one helper ----------
old_anchor = "# ============ runtime_state key 常量 ==============
"
assert old_anchor in src, "runtime_state key anchor not found"
helper_block = (
    old_anchor
    + "

"
    + "COMPILE_TIMEOUT_S: float = 30.0
"
    + "COMPILE_MAX_WORKERS: int = max(2, os.cpu_count() or 1)
"
    + "

"
    + "def _compile_one(path: Path) -> str | None:
"
    + '    """编译单个 .py; 返回 None=OK, str=错误文案."""
'
    + "    try:
"
    + "        py_compile.compile(str(path), doraise=True)
"
    + "    except py_compile.PyCompileError as e:
"
    + "        return str(e)
"
    + "    except OSError as e:
"
    + "        # 读权限/IO 等; 不让单文件坏道阻塞整批
"
    + "        return f"{type(e).__name__}: {e}"
"
    + "    return None
"
)
src = src.replace(old_anchor, helper_block, 1)

# ---------- 3. 重写 _check_compile ----------
m = re.search(
    r"def _check_compile\(repo_root: Path\) -> list\[dict\[str, Any\]\]:
(.*?
)(    return results
)",
    src, flags=re.DOTALL,
)
assert m, "could not isolate _check_compile body"
old_full = m.group(0)

new_full = (
    "def _check_compile(
"
    "    repo_root: Path,
"
    "    timeout_s: float | None = None,
"
    "    max_workers: int | None = None,
"
    ") -> list[dict[str, Any]]:
"
    "    """对 X-repo_root/src 下每个 .py 跑 py_compile (并发 + per-file timeout).

"
    "    Args:
"
    "        repo_root: 仓库根; 用于把绝对路径转 str(Path.relative_to(repo_root))
"
    "            方便 JSONL 日志肉眼可读.
"
    "        timeout_s: 单文件编译软超时 (秒); None 或 X=0 走 COMPILE_TIMEOUT_S
"
    "            (默认 30s).
"
    "        max_workers: 线程池大小; None/X=0 走 COMPILE_MAX_WORKERS
"
    "            (默认 max(2, cpu_count())).

"
    "    Returns:
"
    "        list[dict[str, Any]]: 每条::

"
    '            {"file": X-rel, "ok": True}
'
    "            # 或失败时:
"
    '            {"file": X-rel, "ok": False, "error": X-str}

"
    "        X-repo_root/src 不存在时返回空 list; rglob 自身抛 OSError 时返回
"
    '        [{"file": "src/", "ok": False, "error": "rglob 失败: X-type: X-msg"}]
'
    "        (单元素 list, 让上层 JSONL 至少有 1 条 fail 可读).

"
    "    Notes:
"
    "        per-file 超时不会真正杀掉 worker 线程 (Python 限制), 但 future.result
"
    "        会抛 TimeoutError 让上层拿到一条 error='编译超时 (>Xs)' 的结果;
"
    "        worker 线程收尾时被 executor __exit__ 回收, 不会泄漏.
"
    '    """
'
    "    src_dir = repo_root / "src"
"
    "    if not src_dir.exists():
"
    "        return []
"
    "    try:
"
    "        files = list(src_dir.rglob("*.py"))
"
    "    except OSError as e:
"
    "        return [{
"
    '            "file": "src/",
'
    '            "ok": False,
'
    '            "error": f"rglob 失败: {type(e).__name__}: {e}",
'
    "        }]
"
    "    effective_timeout: float = (
"
    "        COMPILE_TIMEOUT_S if (timeout_s is None or timeout_s <= 0) else timeout_s
"
    "    )
"
    "    workers = (
"
    "        max_workers if (max_workers is not None and max_workers > 0)
"
    "        else COMPILE_MAX_WORKERS
"
    "    )

"
    "    results: list[dict[str, Any]] = []
"
    "    with ThreadPoolExecutor(max_workers=workers) as executor:
"
    "        future_to_py = {executor.submit(_compile_one, py): py for py in files}
"
    "        for future in as_completed(future_to_py):
"
    "            py = future_to_py[future]
"
    "            rel = str(py.relative_to(repo_root))
"
    "            try:
"
    "                err = future.result(timeout=effective_timeout)
"
    "            except FuturesTimeoutError:
"
    "                results.append({
"
    '                    "file": rel, "ok": False,
'
    '                    "error": f"编译超时 (>{effective_timeout}s)",
'
    "                })
"
    "                continue
"
    "            except Exception as e:
"
    "                # 主线程解析 future 时的异常; worker 内异常已被 _compile_one 捕获
"
    "                results.append({
"
    '                    "file": rel, "ok": False,
'
    '                    "error": f"{type(e).__name__}: {e}",
'
    "                })
"
    "                continue
"
    "            if err is None:
"
    '                results.append({"file": rel, "ok": True})
'
    "            else:
"
    '                results.append({"file": rel, "ok": False, "error": err})
'
    "    return results
"
)

src = src.replace(old_full, new_full, 1)

# ---------- 4. propose_self_replace 异常兜底 ----------
old_prop = (
    "    # 正常路径: 完全委托给 module-level metamorphose (single source of truth);
"
    "    # 测试通过 monkeypatch.setattr(evolve_tools, "metamorphose", ...) 拦截.
"
    "    return metamorphose(reason=reason, entry=entry)
"
)
assert old_prop in src, "propose_self_replace tail anchor not found"
new_prop = (
    "    # 正常路径: 完全委托给 module-level metamorphose (single source of truth);
"
    "    # 测试通过 monkeypatch.setattr(evolve_tools, "metamorphose", ...) 拦截.
"
    "    # 兜底 OSError/RuntimeError (eg subprocess 启动失败 / compile 工具链崩):
"
    "    # 不让 LLM 工具调用抛异常, 返回结构化失败; TypeError (参数错) 仍上抛, 那是契约破坏.
"
    "    try:
"
    "        return metamorphose(reason=reason, entry=entry)
"
    "    except (OSError, RuntimeError) as e:
"
    "        return {
"
    '            "ok": False,
'
    '            "error": f"metamorphose 失败: {type(e).__name__}: {e}",
'
    "        }
"
)
src = src.replace(old_prop, new_prop, 1)

# ---------- 5. terminate 写盘 OSError 兜底 ----------
old_term = "    _save_runtime_state(state_path, state)
"
assert old_term in src, "terminate save anchor not found"
new_term = (
    "    # 写盘失败不能让 SIGTERM 卡住: stderr 留痕, 继续往下走
"
    "    try:
"
    "        _save_runtime_state(state_path, state)
"
    "    except OSError as e:
"
    "        print(
"
    "            f"runtime_state 写盘失败: {type(e).__name__}: {e}; reason={reason}",
"
    "            file=sys.stderr,
"
    "        )
"
)
src = src.replace(old_term, new_term, 1)

assert src != orig, "no changes applied"
p.write_text(src, encoding="utf-8")
print(f"patched: {len(orig)} -> {len(src)} bytes ({len(src)-len(orig):+d})")
