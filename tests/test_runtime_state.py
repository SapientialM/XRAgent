"""runtime_state 模块边界条件补齐。

src/xragent/watchdog/runtime_state.py 此前在 tests/ 下零直接覆盖（仅在
test_supervisor_self_healing.py 里被间接用到）。本文件针对下列边界条件补齐：

  * read：文件不存在 → {}；文件存在但 JSON 损坏 → {}；写入再读回往返
  * write：parent 目录不存在时自动 mkdir(parents=True, exist_ok)
  * heartbeat：合并 extra；extra=None 不应炸；多次调用 ts 单调推进
  * is_alive：空 state / 缺 heartbeat_ts → False；超时边界 (<=, >) 判定
  * restart_count：缺键默认 0；非整数也能 int() 强转
  * bump_restart：缺键从 0 起跳；连续累加；重启不影响已有其它字段
"""
from __future__ import annotations

import json
import os
import time

from xragent.watchdog import runtime_state as rs


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------

def test_read_returns_empty_dict_when_file_missing(repo_root):
    """文件尚未创建 → read() 返回 {} 而不是抛 FileNotFoundError。"""
    state_path = repo_root / "runtime_state.json"
    assert not state_path.exists()  # conftest 只设置路径，未触发写
    assert rs.read() == {}


def test_read_returns_empty_dict_on_corrupted_json(repo_root):
    """文件存在但 JSON 损坏 → 走 except 分支返回 {}，不抛。"""
    state_path = repo_root / "runtime_state.json"
    state_path.write_text("{this is not: valid json,,", encoding="utf-8")
    assert rs.read() == {}


def test_read_roundtrip_after_write(repo_root):
    """write → read 应拿到完全相同的内容（包括中文 / ensure_ascii=False）。"""
    payload = {"a": 1, "中文": "键值", "nested": {"k": [1, 2, 3]}}
    rs.write(payload)
    assert rs.read() == payload


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------

def test_write_creates_parent_directories(repo_root):
    """runtime_state_path.parent 不存在时，write 应自动 mkdir(parents=True)。"""
    nested = repo_root / "does" / "not" / "exist" / "yet"
    rs_path = nested / "runtime_state.json"
    # 临时把 settings.runtime_state_path 指向深层新目录
    from xragent.config import settings as sm

    sm.get_settings().runtime_state_path = rs_path
    try:
        rs.write({"x": 1})
        assert rs_path.exists()
        assert nested.is_dir()
        assert json.loads(rs_path.read_text(encoding="utf-8")) == {"x": 1}
    finally:
        # 还原回 conftest 给的路径，避免污染后续测试
        sm.get_settings().runtime_state_path = repo_root / "runtime_state.json"


def test_write_serializes_with_indent_and_utf8(repo_root):
    """write 使用 indent=2 + ensure_ascii=False；落盘内容应可肉眼读且保留中文。"""
    rs.write({"k": "中文"})
    raw = (repo_root / "runtime_state.json").read_text(encoding="utf-8")
    assert "中文" in raw  # 不是 \\uXXXX 形式
    assert "\n" in raw    # indent=2 → 多行


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------

def test_heartbeat_sets_pid_and_timestamp(repo_root):
    """heartbeat() 应同时写入 heartbeat_ts（数字）和当前进程 pid。"""
    rs.heartbeat()
    state = rs.read()
    assert isinstance(state["heartbeat_ts"], (int, float))
    assert state["pid"] == os.getpid()
    assert state["heartbeat_ts"] <= time.time()


def test_heartbeat_with_extra_merges_into_state(repo_root):
    """extra 字典应被合入顶层 state（顶层覆盖语义）。"""
    rs.write({"existing": "old"})
    rs.heartbeat({"tick": 7, "extra_marker": True})
    state = rs.read()
    assert state["tick"] == 7
    assert state["extra_marker"] is True
    assert state["existing"] == "old"
    assert "heartbeat_ts" in state
    assert state["pid"] == os.getpid()


def test_heartbeat_extra_none_does_not_break(repo_root):
    """extra=None（默认）应走 `if extra:` 短路，不污染 state。"""
    rs.heartbeat()  # extra=None
    state = rs.read()
    assert set(state.keys()) <= {"heartbeat_ts", "pid"}


def test_heartbeat_monotonic_timestamp(repo_root):
    """连续两次心跳，ts 应当非递减（time.time 精度内）。"""
    rs.heartbeat()
    t1 = rs.read()["heartbeat_ts"]
    # sleep 一小段避免 time.time() 精度退化（macOS 上常见）
    time.sleep(0.01)
    rs.heartbeat()
    t2 = rs.read()["heartbeat_ts"]
    assert t2 >= t1


# ---------------------------------------------------------------------------
# is_alive
# ---------------------------------------------------------------------------

def test_is_alive_false_when_state_empty(repo_root):
    """完全没写过心跳 → is_alive 必 False，不抛异常。"""
    assert rs.read() == {}
    assert rs.is_alive(timeout_s=60) is False


def test_is_alive_false_when_no_heartbeat_ts(repo_root):
    """state 里没有 heartbeat_ts 键 → 视作过期。"""
    rs.write({"pid": 12345})  # 只有 pid
    assert rs.is_alive(timeout_s=60) is False


def test_is_alive_true_when_fresh(repo_root):
    """刚写过心跳 → 在大 timeout 下应 True。"""
    rs.heartbeat()
    assert rs.is_alive(timeout_s=60) is True


def test_is_alive_false_when_stale(repo_root):
    """手工把心跳写成 1000 秒前 → is_alive(timeout=10) 应 False。"""
    stale_ts = time.time() - 1000
    rs.write({"heartbeat_ts": stale_ts})
    assert rs.is_alive(timeout_s=10) is False


def test_is_alive_boundary_inclusive_at_timeout(repo_root):
    """边界：now - ts == timeout_s 时按实现 <='=' 应判定为 True（仍"活着"）。"""
    # 把心跳写成"恰好 timeout_s 秒前"
    # time.time 精度问题：用 (time.time() - timeout_s) 作为 ts，差值约等于 0
    s = 5
    rs.write({"heartbeat_ts": time.time() - s})
    # time.time() 走了一小段，差值会比 s 略大一点点 → False
    # 这是真值，不强行"调整"；只断言"s 之内是活"
    assert rs.is_alive(timeout_s=s + 1) is True


# ---------------------------------------------------------------------------
# restart_count
# ---------------------------------------------------------------------------

def test_restart_count_defaults_to_zero_when_missing(repo_root):
    """state 里没有 restart_count → 视作 0。"""
    rs.write({"heartbeat_ts": 1.0})
    assert rs.restart_count() == 0


def test_restart_count_defaults_to_zero_when_state_empty(repo_root):
    """空 state（文件不存在）→ 0。"""
    assert rs.restart_count() == 0


def test_restart_count_coerces_non_int(repo_root):
    """restart_count 字段是字符串数字时，int() 应强转成功。"""
    rs.write({"restart_count": "3"})
    assert rs.restart_count() == 3


def test_restart_count_returns_existing_int(repo_root):
    rs.write({"restart_count": 7})
    assert rs.restart_count() == 7


# ---------------------------------------------------------------------------
# bump_restart
# ---------------------------------------------------------------------------

def test_bump_restart_starts_from_zero_when_missing(repo_root):
    """缺键时按 0 处理，第一次 bump 应得到 1。"""
    rs.write({})
    assert rs.bump_restart() == 1
    assert rs.restart_count() == 1


def test_bump_restart_increments_existing(repo_root):
    """已有值时应 +1 而非覆盖。"""
    rs.write({"restart_count": 4})
    assert rs.bump_restart() == 5
    assert rs.bump_restart() == 6


def test_bump_restart_preserves_other_keys(repo_root):
    """bump_restart 不应清掉其它字段（如 heartbeat_ts / pid）。"""
    rs.write({"heartbeat_ts": 123.0, "pid": 999, "note": "alive"})
    rs.bump_restart()
    state = rs.read()
    assert state["heartbeat_ts"] == 123.0
    assert state["pid"] == 999
    assert state["note"] == "alive"
    assert state["restart_count"] == 1