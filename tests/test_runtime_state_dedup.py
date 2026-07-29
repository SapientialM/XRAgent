"""验证 metamorphose / terminate 已统一走 runtime_state.read/write。

之前的 metamorphosis.py / evolve_tools.py 各有一份手写的"文件存在 → json.loads
→ except → state={}" + "write_text(json.dumps(..., indent=2))" 模板。本文件
证明重构后两份代码仍正确把 state 写入 runtime_state.json，且与原实现的
行为等价（中文保留 / indent 多行 / 不丢旧字段）。
"""
from __future__ import annotations

import json
from unittest.mock import patch

from xragent.evolve.metamorphosis import metamorphose
from xragent.tools import evolve_tools
from xragent.tools.evolve_tools import terminate


def test_metamorphose_writes_metamorphosis_pending_via_runtime_state(repo_root):
    """metamorphose() 应把 metamorphosis_pending 写入 runtime_state.json。"""
    src = repo_root / "src"
    src.mkdir(exist_ok=True)
    (src / "ok.py").write_text("ok = True\n", encoding="utf-8")

    res = metamorphose("refactor dedup")

    state_path = repo_root / "runtime_state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    pending = state["metamorphosis_pending"]
    assert pending["reason"] == "refactor dedup"
    assert pending["entry"] == "src/xragent/main.py"
    assert pending["compile_ok"] is True
    assert pending["new_head"] == res["head_after"]
    assert isinstance(pending["ts"], (int, float))


def test_metamorphose_preserves_existing_state_keys(repo_root):
    """metamorphose() 应在已有 state 上叠加 metamorphosis_pending，不丢旧字段。"""
    src = repo_root / "src"
    src.mkdir(exist_ok=True)
    (src / "ok.py").write_text("ok = True\n", encoding="utf-8")

    # 预先写入其它字段
    state_path = repo_root / "runtime_state.json"
    state_path.write_text(
        json.dumps(
            {"heartbeat_ts": 123.0, "pid": 999, "custom_note": "keep me"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    metamorphose("preserve keys")

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["heartbeat_ts"] == 123.0
    assert state["pid"] == 999
    assert state["custom_note"] == "keep me"
    assert "metamorphosis_pending" in state


def test_metamorphose_writes_utf8_with_indent(repo_root):
    """落盘内容应可肉眼读且保留中文（与原实现一致的 ensure_ascii=False + indent）。"""
    src = repo_root / "src"
    src.mkdir(exist_ok=True)
    (src / "ok.py").write_text("ok = True\n", encoding="utf-8")

    metamorphose("中文 reason 保留")

    raw = (repo_root / "runtime_state.json").read_text(encoding="utf-8")
    assert "中文 reason 保留" in raw  # 不是 \\uXXXX
    assert "\n" in raw               # indent=2


def test_terminate_writes_restart_suppressed_and_reason(repo_root, monkeypatch):
    """terminate() 应把 restart_suppressed / terminate_reason 写入 runtime_state.json。

    os.kill(SIGTERM) 会真杀本进程；用 monkeypatch 替换掉。
    """
    # 防止真发 SIGTERM
    monkeypatch.setattr(evolve_tools.os, "kill", lambda *a, **kw: None)

    res = terminate("dedup test")

    assert res == {"ok": True, "reason": "dedup test"}
    state = json.loads((repo_root / "runtime_state.json").read_text(encoding="utf-8"))
    assert state["restart_suppressed"] is True
    assert state["terminate_reason"] == "dedup test"


def test_terminate_preserves_existing_state(repo_root, monkeypatch):
    """terminate() 走 rs_read()/rs_write() 路径，不应丢 state 已有字段。"""
    monkeypatch.setattr(evolve_tools.os, "kill", lambda *a, **kw: None)

    state_path = repo_root / "runtime_state.json"
    state_path.write_text(
        json.dumps(
            {"metamorphosis_pending": {"reason": "earlier"}, "note": "alive"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    terminate("preserve existing")

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["metamorphosis_pending"] == {"reason": "earlier"}
    assert state["note"] == "alive"
    assert state["restart_suppressed"] is True
    assert state["terminate_reason"] == "preserve existing"


def test_metamorphose_handles_missing_runtime_state_file(repo_root):
    """runtime_state.json 不存在时，metamorphose() 仍应能写出新文件（与原 if/except 等价）。"""
    state_path = repo_root / "runtime_state.json"
    assert not state_path.exists()

    src = repo_root / "src"
    src.mkdir(exist_ok=True)
    (src / "ok.py").write_text("ok = True\n", encoding="utf-8")

    metamorphose("first run, no state")

    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["metamorphosis_pending"]["reason"] == "first run, no state"


def test_terminate_handles_missing_runtime_state_file(repo_root, monkeypatch):
    """runtime_state.json 不存在时，terminate() 仍应能写出新文件。"""
    state_path = repo_root / "runtime_state.json"
    assert not state_path.exists()
    monkeypatch.setattr(evolve_tools.os, "kill", lambda *a, **kw: None)

    terminate("cold start")

    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["restart_suppressed"] is True
    assert state["terminate_reason"] == "cold start"