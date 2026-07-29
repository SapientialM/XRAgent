"""Safe JSON 解析工具。

把"try/except json.JSONDecodeError 兜底"模式从各处抽出来：
  - autonomous.py 解析 queue.jsonl 单行
  - http_server.py 解析 HTTP 请求体

两处原本各写一遍 4-5 行的 try/except 块；抽到一处后，
调用方只需 ``rec = safe_json_loads(text); if rec is not None: ...``。
"""
from __future__ import annotations

import json
from typing import Any


def safe_json_loads(text: "str | bytes | None") -> Any | None:
    """解析 JSON 文本；失败（含 ``ValueError`` / ``TypeError`` 等）一律返回 ``None``。

    与直接 ``json.loads`` 的区别：
      * 任何异常（不只 ``JSONDecodeError``）都被吞掉，调用方不用再包 try
      * 失败约定是 ``None``——调用方用 ``is None`` 判断；不要把 ``None`` 当合法 JSON 值用
      * 输入为 ``None`` 时直接短路返回 ``None``（避免异常机制开销）

    返回类型故意保持宽（``Any``），因为调用方通常马上 ``.get(...)``；
    抽到 typed 返回会逼着每个调用方先 cast，得不偿失。

    Note:
        ``json.loads("null")`` 会返回 ``None``，与"解析失败"无法区分。
        调用方如果需要区分，请自行 ``text != "null" and text is not None``，
        或改用 ``json.loads`` + 自己 try/except。

    Examples:
        >>> safe_json_loads('{"a": 1}')
        {'a': 1}
        >>> safe_json_loads("not json") is None
        True
        >>> safe_json_loads(None) is None
        True
        >>> safe_json_loads(b'{"x": 2}')
        {'x': 2}
    """
    if text is None:
        # 边界：显式 None → 显式 None；省去 json.loads 抛 TypeError 的开销。
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        # ValueError 覆盖 json.JSONDecodeError（其基类）；
        # TypeError 覆盖 dict / list 等"非 str/bytes 类型"的情况。
        return None