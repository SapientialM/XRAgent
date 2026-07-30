"""JSON state 文件读写工具。

把"读 + 解析 + 失败兜底"和"mkdir parent + 序列化 + write"模板从 3 处抽出来：
  - ``watchdog.runtime_state.read``/``write``：管理 ``runtime_state.json``
  - ``tools.web_search._read_state``/``_write_state``：管理 ``.web_fetch_state.json``
  - ``evolve.metamorphosis`` + ``tools.evolve_tools.terminate``：以前手写 7 行
    ``if exists → try read → except → state={}`` + ``write_text(json.dumps)``

3 处的行为需求完全一致：
  * 读：文件不存在或解析失败一律返回 ``default``（不抛错，让上层少一层 try）
  * 写：父目录不存在时自动 ``mkdir(parents=True)``；保留中文（``ensure_ascii=False``）；
    默认 ``indent=2`` 便于人工 cat

抽到一处后调用方只需 ``read_json_state(path)`` / ``write_json_state(path, state)``,
行为统一,坏文件不再让上层崩。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .json_utils import safe_json_loads


def read_json_state(path: Path, default: Any | None = None) -> Any:
    """读 JSON state 文件;不存在或解析失败返回 ``default``。

    Args:
        path: JSON 文件路径。
        default: 缺失/坏行时返回的兜底值;``None`` 时返回 ``None``
            （与 ``safe_json_loads`` 的失败约定一致）。

    Returns:
        解析后的对象;文件不存在 / 解析失败 / 内容为空时返回 ``default``。

    Note:
        这里故意吞掉所有异常（不只 ``JSONDecodeError``），因为 state 文件
        经常被多进程并发写，半行 / 截断 / 非 dict 内容都会出现；
        让上层拿到 ``default`` 然后继续走，比抛异常更安全。
    """
    if not path.exists():
        return default
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return default
    if not text.strip():
        # 空文件视作缺失：避免 json.loads("") 抛 JSONDecodeError
        return default
    parsed = safe_json_loads(text)
    if parsed is None:
        return default
    return parsed


def write_json_state(path: Path, state: Any, *, indent: int = 2) -> None:
    """写 JSON state 文件;自动 ``mkdir(parents=True)`` + 保留中文。

    Args:
        path: 目标 JSON 路径;父目录会自动创建。
        state: 任意可被 ``json.dumps`` 序列化的对象。
        indent: JSON indent;默认 ``2`` 便于人工 ``cat`` 检查。``None``/0
            时单行输出（紧凑模式，给非人类读的配置文件用）。

    Note:
        ``ensure_ascii=False`` 是有意的：state 文件体积小，人类肉眼读比
        字节数更重要；统一规范避免各调用方写不一致。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=indent)
    path.write_text(payload, encoding="utf-8")