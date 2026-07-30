"""``util/json_state`` 模块边界条件补齐。

重构前 ``read_json_state`` / ``write_json_state`` 是 3 处手写模板
（``watchdog.runtime_state`` + ``tools.web_search._read_state/_write_state`` +
``evolve.metamorphosis`` + ``tools.evolve_tools.terminate``），每处都各自 try/except
JSONDecodeError / 处理 mkdir parent / 选 indent。新 utility 把这些行为集中到
一处,本测试保证行为统一且不丢边界场景。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from xragent.util.json_state import read_json_state, write_json_state


# --- read_json_state ------------------------------------------------------


def test_read_missing_file_returns_default(tmp_path: Path):
    """文件不存在时返 default(默认 None)而不抛 FileNotFoundError。"""
    assert read_json_state(tmp_path / "nope.json") is None
    assert read_json_state(tmp_path / "nope.json", default={}) == {}


def test_read_empty_file_returns_default(tmp_path: Path):
    """空文件视作缺失（不抛 JSONDecodeError）。"""
    p = tmp_path / "empty.json"
    p.write_text("", encoding="utf-8")
    assert read_json_state(p) is None
    assert read_json_state(p, default=[]) == []


def test_read_malformed_json_returns_default(tmp_path: Path):
    """坏行（截断/语法错）静默返回 default,不让上层崩。"""
    p = tmp_path / "broken.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert read_json_state(p, default={}) == {}


def test_read_valid_dict(tmp_path: Path):
    """正常 dict 文件能读出。"""
    p = tmp_path / "ok.json"
    p.write_text(json.dumps({"a": 1, "b": [2, 3]}, ensure_ascii=False), encoding="utf-8")
    assert read_json_state(p) == {"a": 1, "b": [2, 3]}


def test_read_preserves_unicode(tmp_path: Path):
    """utf-8 中文保留（ensure_ascii=False 一致性）。"""
    p = tmp_path / "cn.json"
    p.write_text(json.dumps({"reason": "中文 reason"}, ensure_ascii=False), encoding="utf-8")
    assert read_json_state(p) == {"reason": "中文 reason"}


def test_read_accepts_non_dict_default(tmp_path: Path):
    """default 类型由调用方决定;这里验 list[int] 也能 round-trip。"""
    p = tmp_path / "list.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert read_json_state(p, default=[]) == [1, 2, 3]


# --- write_json_state -----------------------------------------------------


def test_write_creates_parent_dirs(tmp_path: Path):
    """父目录不存在时自动 mkdir(parents=True)——对应 4 处原代码的 mkdir 行。"""
    deep = tmp_path / "a" / "b" / "c" / "state.json"
    write_json_state(deep, {"k": 1})
    assert deep.exists()
    assert json.loads(deep.read_text(encoding="utf-8")) == {"k": 1}


def test_write_default_indent_is_2(tmp_path: Path):
    """默认 indent=2(便于人类 cat 检查)。"""
    p = tmp_path / "ind.json"
    write_json_state(p, {"a": 1, "b": 2})
    raw = p.read_text(encoding="utf-8")
    assert "\n" in raw  # 多行
    assert '"a": 1' in raw and '"b": 2' in raw


def test_write_preserves_unicode(tmp_path: Path):
    """中文不转 \\uXXXX(ensure_ascii=False 一致性,与 4 处原实现等价)。"""
    p = tmp_path / "cn.json"
    write_json_state(p, {"reason": "中文 reason 保留"})
    raw = p.read_text(encoding="utf-8")
    assert "中文 reason 保留" in raw


def test_write_compact_mode(tmp_path: Path):
    """indent=None 时单行输出。"""
    p = tmp_path / "compact.json"
    write_json_state(p, {"a": 1, "b": 2}, indent=None)
    raw = p.read_text(encoding="utf-8")
    assert "\n" not in raw


def test_write_overwrites_existing(tmp_path: Path):
    """写覆盖(不是 append);与 4 处原实现 write_text 行为一致。"""
    p = tmp_path / "ov.json"
    write_json_state(p, {"v": 1})
    write_json_state(p, {"v": 2})
    assert read_json_state(p) == {"v": 2}


# --- round-trip -----------------------------------------------------------


def test_roundtrip_preserves_keys_and_nesting(tmp_path: Path):
    """嵌套 dict list round-trip 不丢字段。"""
    p = tmp_path / "rt.json"
    state = {"a": 1, "nested": {"x": [1, 2, 3], "y": "z"}, "empty": [], "none": None}
    write_json_state(p, state)
    assert read_json_state(p) == state


# --- 行为统一性：与 3 处原实现的格式契约 ----------------------------------


def test_format_matches_legacy_runtime_state_write(tmp_path: Path):
    """落盘格式应与原 ``watchdog.runtime_state.write`` 一致:

    - ``ensure_ascii=False``(中文直接写,不转义)
    - ``indent=2``(多行 + 2 空格缩进)

    这是 ``test_runtime_state_dedup.py::test_metamorphose_writes_utf8_with_indent``
    已隐含的契约;这里在 utility 层面再固化一次。
    """
    p = tmp_path / "f.json"
    write_json_state(p, {"中文": "reason"})
    raw = p.read_text(encoding="utf-8")
    assert "中文" in raw and "\\u" not in raw
    # indent=2: 顶层 key 前面应有 2 空格
    assert "  \"中文\"" in raw


def test_format_matches_legacy_web_search_write(tmp_path: Path):
    """``web_fetch_state.json`` 落盘格式应与原 ``_write_state`` 一致。

    原实现用 ``indent=2`` + ``ensure_ascii=False``,这里保持不变,
    ``test_runtime_state_dedup.py::test_metamorphose_writes_utf8_with_indent``
    已经隐式覆盖;此处显式再固化一次以防 utility 改格式时悄无声息破坏
    curl 限流持久化文件。
    """
    p = tmp_path / "ws.json"
    write_json_state(p, {"last_curl_ts": 123.0, "last_url": "https://example.com/中文"})
    raw = p.read_text(encoding="utf-8")
    assert "中文" in raw
    assert "  \"last_curl_ts\"" in raw