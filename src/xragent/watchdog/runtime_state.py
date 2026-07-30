"""运行时状态读写封装。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from ..config.settings import get_settings


def _path() -> Path:
    """解析 runtime_state.json 的目标路径。

    Returns:
        Path: ``Settings.runtime_state_path`` 指向的路径；解析时机为调用瞬间。
    """
    return get_settings().runtime_state_path


def _coerce_int(value: Any, default: int) -> int:
    """把任意值强转 ``int``；失败（``TypeError`` / ``ValueError``）回退 ``default``。

    与裸 ``int(value)`` 的区别：把"键存在但值为 ``None``"或"非数字字符串"这类
    边界统一收敛到 ``default``，避免调用方再写 try/except。
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def read() -> dict[str, Any]:
    """读取运行时状态。

    Returns:
        dict[str, Any]: 当前 state。文件不存在或 JSON 损坏时返回空字典
            （不抛 FileNotFoundError / json.JSONDecodeError）。
    """
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write(state: dict[str, Any]) -> None:
    """原子写覆盖 runtime_state.json。

    会自动 ``mkdir -p`` 父目录（``parents=True, exist_ok=True``），便于首次启动。

    Args:
        state: 待持久化的字典；用 ``ensure_ascii=False`` + ``indent=2`` 序列化，
            中文可肉眼读。

    Side effects:
        写文件；可能创建多层父目录。
    """
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def heartbeat(extra: dict[str, Any] | None = None) -> None:
    """刷新心跳时间戳 + 当前 pid，可选合并附加字段。

    先 ``read()`` 再 ``write()``，不是原子操作；并发心跳可能丢失更新，
    当前 watchdog 设计仅单进程写，不构成问题。

    Args:
        extra: 额外写入的字段（如 ``{"tick": N}``）；为 ``None`` 或空 dict
            时不污染 state。

    Side effects:
        写文件；自动覆盖 ``heartbeat_ts`` / ``pid`` 两个键。
    """
    state = read()
    state["heartbeat_ts"] = time.time()
    state["pid"] = os.getpid()
    if extra:
        state.update(extra)
    write(state)


def is_alive(timeout_s: int) -> bool:
    """判断 watchdog 目标是否仍在心跳窗口内。

    Args:
        timeout_s: 心跳过期阈值（秒）。

    Returns:
        bool: ``heartbeat_ts`` 存在且 ``now - ts <= timeout_s`` 时为 True；
            缺键或 JSON 损坏视为过期（False）。
    """
    state = read()
    ts = state.get("heartbeat_ts")
    if ts is None:
        return False
    return (time.time() - ts) <= timeout_s


def restart_count() -> int:
    """读取累计重启次数。

    Returns:
        int: ``state["restart_count"]``；缺键返回 0，非整数经 ``_coerce_int``
            强转（含 ``None`` / 非数字字符串回退到 0）。
    """
    return _coerce_int(read().get("restart_count", 0), 0)


def bump_restart() -> int:
    """递增重启计数并写回。

    缺键或值为 ``None`` 时从 0 起跳；已有值则 ``+1``。其它字段
    （``heartbeat_ts`` / ``pid`` 等）不受影响。

    Returns:
        int: 递增后的新值。
    """
    state = read()
    state["restart_count"] = _coerce_int(state.get("restart_count"), 0) + 1
    write(state)
    return state["restart_count"]