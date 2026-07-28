"""MockBackend 的覆盖测试。

之前 MockBackend.__init__ 的 script_path 加载路径没有任何单元测试，
这一组测试覆盖：
  - 默认剧本（无 script_path）
  - 从脚本文件加载
  - 跳过空行/纯空白行
  - UTF-8 编码内容（验证 encoding 参数生效）
  - 文件不存在时回退默认
  - cursor 在剧本里循环
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from xragent.core.backend import MockBackend


@pytest.fixture
def script_file(tmp_path: Path) -> Path:
    """一个最小的合法 mock 脚本。"""
    p = tmp_path / "script.jsonl"
    lines = [
        {"content": "你好，我是息壤。", "finish_reason": "stop"},
        {"content": "我在听。", "finish_reason": "stop"},
    ]
    p.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in lines) + "\n", encoding="utf-8")
    return p


def test_no_script_path_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """无 script_path 参数且环境变量未设，回退 DEFAULT_SCRIPT。"""
    monkeypatch.delenv("XRAGENT_MOCK_SCRIPT", raising=False)
    b = MockBackend(script_path=None)
    assert len(b._script) == len(MockBackend.DEFAULT_SCRIPT)
    t = b.chat(messages=[], tools=[])
    assert t.content == MockBackend.DEFAULT_SCRIPT[0]["content"]


def test_missing_file_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """script_path 指向不存在的文件，不抛错，回退 DEFAULT_SCRIPT。"""
    monkeypatch.delenv("XRAGENT_MOCK_SCRIPT", raising=False)
    b = MockBackend(script_path="/nonexistent/path/should/not/exist.jsonl")
    assert len(b._script) == len(MockBackend.DEFAULT_SCRIPT)


def test_loads_valid_script(script_file: Path) -> None:
    """从有效脚本逐行加载。"""
    b = MockBackend(script_path=str(script_file))
    assert len(b._script) == 2
    assert b._script[0].content == "你好，我是息壤。"
    assert b._script[1].content == "我在听。"


def test_skips_empty_and_whitespace_lines(tmp_path: Path) -> None:
    """脚本里有空行/纯空白行，应当被忽略，不抛 json 解析错误。"""
    p = tmp_path / "noisy.jsonl"
    p.write_text(
        "\n"
        '   \n'
        + json.dumps({"content": "first", "finish_reason": "stop"}, ensure_ascii=False)
        + "\n"
        "\t  \n"
        + json.dumps({"content": "second", "finish_reason": "stop"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    b = MockBackend(script_path=str(p))
    assert len(b._script) == 2
    assert [t.content for t in b._script] == ["first", "second"]


def test_non_ascii_content_is_decoded_via_utf8(tmp_path: Path) -> None:
    """非 ASCII 内容必须能正确解码 —— 这是显式指定 encoding='utf-8' 的目的。"""
    p = tmp_path / "utf8.jsonl"
    payload = {"content": "息 · 一抔能自生长的土", "finish_reason": "stop"}
    # 显式 utf-8 写
    p.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    b = MockBackend(script_path=str(p))
    assert b._script[0].content == "息 · 一抔能自生长的土"


def test_empty_script_file_falls_back_to_default(tmp_path: Path) -> None:
    """脚本文件存在但内容为空 → self._script 为空 → 回退 DEFAULT_SCRIPT。"""
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    b = MockBackend(script_path=str(p))
    assert len(b._script) == len(MockBackend.DEFAULT_SCRIPT)


def test_cursor_cycles_through_script(script_file: Path) -> None:
    """cursor 应当从头到尾循环，而不是在末尾抛 IndexError。"""
    b = MockBackend(script_path=str(script_file))
    contents = [b.chat(messages=[], tools=[]).content for _ in range(5)]
    assert contents[:2] == ["你好，我是息壤。", "我在听。"]
    # 之后回到第一句、再到第二句
    assert contents[2] == "你好，我是息壤。"
    assert contents[3] == "我在听。"
    assert contents[4] == "你好，我是息壤。"


def test_invalid_json_line_raises(tmp_path: Path) -> None:
    """坏 JSON 行应当让 __init__ 抛 json.JSONDecodeError（契约不变）。

    这是显式的边界行为 —— 改动不应该悄悄改变它。
    """
    p = tmp_path / "bad.jsonl"
    p.write_text("not valid json\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        MockBackend(script_path=str(p))


def test_tool_calls_are_parsed(tmp_path: Path) -> None:
    """脚本里带 tool_calls 也能正确解析为 ToolCall 对象。"""
    p = tmp_path / "with_tools.jsonl"
    payload = {
        "content": "",
        "finish_reason": "tool_calls",
        "tool_calls": [{"name": "read_file", "args": {"path": "AGENTS.md"}, "id": "abc"}],
    }
    p.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    b = MockBackend(script_path=str(p))
    assert len(b._script[0].tool_calls) == 1
    tc = b._script[0].tool_calls[0]
    assert tc.name == "read_file"
    assert tc.args == {"path": "AGENTS.md"}
    assert tc.id == "abc"
