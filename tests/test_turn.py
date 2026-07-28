"""TurnRecord / TraceRecorder / new_turn_id：格式不变性。

new_turn_id 的关键设计：
  * 格式：``YYYYMMDD-HHMMSS-mmm``
  * 三段（日期前缀、HHMMSS、毫秒后缀）必须派生自**同一次** ``time.time()``
    调用。否则在跨秒边界（T.sss=999 → T+1.001）会写出一个 ID 时间戳错位 1 秒
    的 jsonl 文件，破坏回放排序。这是 race fix 的核心。

> 注：同 ms 内两次调用会得到相同 id —— 这是设计合同（id 精度只到 ms），
> 唯一性由调用方用 pid/序列号补足。我们不在这里测"超 ms 精度的唯一性"。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from xragent.core.turn import TraceRecorder, TurnRecord, new_turn_id


# ---------------------------------------------------------------------------
# new_turn_id：格式不变性
# ---------------------------------------------------------------------------

_ID_PATTERN = re.compile(r"^(\d{8})-(\d{6})-(\d{3})$")


def test_new_turn_id_matches_canonical_format():
    """锁死格式 YYYYMMDD-HHMMSS-mmm。"""
    tid = new_turn_id()
    m = _ID_PATTERN.match(tid)
    assert m is not None, f"id 不匹配格式: {tid!r}"


def test_new_turn_id_segments_are_well_formed():
    """日期段、时间段、毫秒段的取值范围。"""
    tid = new_turn_id()
    date_part, time_part, ms_part = _ID_PATTERN.match(tid).groups()

    # 日期：YYYYMMDD
    y, mo, d = int(date_part[:4]), int(date_part[4:6]), int(date_part[6:8])
    assert 2000 <= y <= 2999
    assert 1 <= mo <= 12
    assert 1 <= d <= 31

    # 时间：HHMMSS
    h, mi, s = int(time_part[:2]), int(time_part[2:4]), int(time_part[4:6])
    assert 0 <= h <= 23
    assert 0 <= mi <= 59
    assert 0 <= s <= 59

    # 毫秒：000..999
    assert 0 <= int(ms_part) <= 999


def test_new_turn_id_consistent_segments_from_single_time_call():
    """race fix 的可观察行为：日期/时间前缀与毫秒后缀互相一致。

    把 time.time monkeypatch 成固定值之后，前缀 strftime 和 ms 后缀都从同一
    时间戳派生。新实现的形式保证了这一点（旧实现分两次调，存在跨秒隐患）。

    注：如果 monkeypatch 没生效，断言会因字符串不匹配而失败 —— 这是想要的行为，
    它会提醒我们实现的可测性。
    """
    sentinel_ts = 1_700_000_000.123  # 2023-11-14 22:13:20 UTC
    expected_local = time.localtime(sentinel_ts)
    expected_prefix = time.strftime("%Y%m%d-%H%M%S", expected_local)
    expected_ms = int(sentinel_ts * 1000) % 1000

    monkey = pytest.MonkeyPatch()
    fake_mod = type("FakeTime", (), {})()
    fake_mod.time = lambda: sentinel_ts
    fake_mod.localtime = time.localtime
    fake_mod.strftime = time.strftime
    try:
        # 整体替换 xragent.core.turn 引用的 time 模块对象
        monkey.setattr("xragent.core.turn.time", fake_mod, raising=True)
        tid = new_turn_id()
    finally:
        monkey.undo()

    assert tid == f"{expected_prefix}-{expected_ms:03d}", (
        f"同一次 time.time() 派生的前缀与后缀应当自洽，got {tid!r}, "
        f"expected {expected_prefix}-{expected_ms:03d}"
    )


# ---------------------------------------------------------------------------
# TurnRecord：序列化
# ---------------------------------------------------------------------------

def test_turn_record_to_jsonl_roundtrip_preserves_all_fields():
    rec = TurnRecord(
        turn_id="20231114-221320-123",
        ts=1_700_000_000.5,
        think="hello",
        action={"actions": [{"tool": "read_file", "args": {"path": "a"}}]},
        observation={"observations": [{"tool": "read_file", "result": {"ok": True}}]},
        score=0.9,
        tokens_in=10,
        tokens_out=20,
        wall_ms=42,
        error=None,
    )
    line = rec.to_jsonl()
    parsed = json.loads(line)
    assert parsed["turn_id"] == "20231114-221320-123"
    assert parsed["ts"] == 1_700_000_000.5
    assert parsed["think"] == "hello"
    assert parsed["action"]["actions"][0]["tool"] == "read_file"
    assert parsed["observation"]["observations"][0]["result"]["ok"] is True
    assert parsed["score"] == 0.9
    assert parsed["tokens_in"] == 10
    assert parsed["tokens_out"] == 20
    assert parsed["wall_ms"] == 42
    assert parsed["error"] is None


def test_turn_record_to_jsonl_handles_unicode():
    rec = TurnRecord(
        turn_id="x", ts=0.0,
        think="中文 + emoji 🐉",
        action=None, observation=None,
    )
    parsed = json.loads(rec.to_jsonl())
    assert parsed["think"] == "中文 + emoji 🐉"


def test_turn_record_defaults():
    """未指定的字段应有 dataclass 默认值。"""
    rec = TurnRecord(turn_id="x", ts=0.0, think="", action=None, observation=None)
    assert rec.score is None
    assert rec.tokens_in == 0
    assert rec.tokens_out == 0
    assert rec.wall_ms == 0
    assert rec.error is None


# ---------------------------------------------------------------------------
# TraceRecorder
# ---------------------------------------------------------------------------

def test_trace_recorder_creates_dir_if_missing(tmp_path: Path):
    target = tmp_path / "nested" / "turns"
    assert not target.exists()
    rec = TraceRecorder(turns_dir=target)
    assert rec.dir == target
    assert target.is_dir()


def test_trace_recorder_write_appends_one_jsonl_line_per_call(tmp_path: Path):
    rec = TraceRecorder(turns_dir=tmp_path)
    r1 = TurnRecord(turn_id="t1", ts=1.0, think="a", action=None, observation=None)
    r2 = TurnRecord(turn_id="t2", ts=2.0, think="b", action=None, observation=None)
    p1 = rec.write(r1)
    p2 = rec.write(r2)
    assert p1 == tmp_path / "t1.jsonl"
    assert p2 == tmp_path / "t2.jsonl"
    # t1 / t2 各落一行
    t1_content = (tmp_path / "t1.jsonl").read_text(encoding="utf-8").strip().splitlines()
    t2_content = (tmp_path / "t2.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(t1_content) == 1
    assert len(t2_content) == 1
    assert json.loads(t1_content[0])["turn_id"] == "t1"
    assert json.loads(t2_content[0])["turn_id"] == "t2"


def test_trace_recorder_write_is_append(tmp_path: Path):
    """同一 turn_id 多次 write → 文件累加（jsonl append 语义）。"""
    rec = TraceRecorder(turns_dir=tmp_path)
    rec.write(TurnRecord(turn_id="same", ts=1.0, think="first", action=None, observation=None))
    rec.write(TurnRecord(turn_id="same", ts=2.0, think="second", action=None, observation=None))
    content = (tmp_path / "same.jsonl").read_text(encoding="utf-8")
    lines = [ln for ln in content.splitlines() if ln]
    assert len(lines) == 2
    assert json.loads(lines[0])["think"] == "first"
    assert json.loads(lines[1])["think"] == "second"


def test_trace_recorder_filename_equals_turn_id(tmp_path: Path):
    """文件名必须 = turn_id.jsonl —— 任何其他命名都会让回放/检索断裂。"""
    rec = TraceRecorder(turns_dir=tmp_path)
    p = rec.write(TurnRecord(turn_id="20231114-221320-123", ts=0.0, think="", action=None, observation=None))
    assert p.name == "20231114-221320-123.jsonl"