"""tools 层 7.x 重构的小修集合 —— 边界 + 不破坏现有契约。

覆盖的改造点:
  fs_tools:
    - 抽 _sandbox_resolve(): read/list/write 三处共享围栏+黑名单解析
    - read_file 加 MAX_READ_BYTES 上限
    - write_file 加 MAX_WRITE_BYTES 上限 + content 类型校验
  registry:
    - 抽 _safe_call(): handler 异常 → {"ok": False, "error": "..."}
  memory_tools:
    - 加 type hints + 返回字典形状文档化

不在本测试覆盖:
  - exec_tools: 仅 docstring 微调, 无行为变化 (test_exec_tools.py 已覆盖)
  - web_search: 未改动

注：本文件用 monkeypatch 改 MAX_*_BYTES 到小值, 避免构造 200KB+ 字符串拖慢测试。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from xragent.tools import fs_tools, memory_tools
from xragent.tools.fs_tools import (
    MAX_READ_BYTES,
    MAX_WRITE_BYTES,
    _sandbox_resolve,
    read_file,
    write_file,
)
from xragent.tools.registry import ToolDef, ToolRegistry, _safe_call


# ===========================================================================
# _sandbox_resolve helper
# ===========================================================================


def test_sandbox_resolve_returns_target_on_inside(repo_root: Path):
    """仓库内合法路径 → (Path, None)。"""
    target, err = _sandbox_resolve("sandbox/note.txt", writable=False)
    assert err is None
    assert target is not None
    # 路径是 absolute 且 normalize 后仍在 repo_root 之下
    assert target.is_absolute()
    assert str(target).startswith(str(repo_root))


def test_sandbox_resolve_returns_err_dict_on_outside(repo_root: Path):
    """围栏外路径 → (None, ok=False 字典)。"""
    target, err = _sandbox_resolve("/etc/passwd", writable=False)
    assert target is None
    assert err is not None
    assert err["ok"] is False
    assert "目标越界" in err["error"]


def test_sandbox_resolve_writable_true_blocks_protected_path(repo_root: Path):
    """writable=True 时, 黑名单路径 (AGENTS.md) 仍被拒绝 ——
    保证 read/list 用 writable=False 不查黑名单, 而 write 仍受保护。
    """
    target, err = _sandbox_resolve("AGENTS.md", writable=True)
    assert target is None
    assert err is not None
    assert err["ok"] is False
    # 黑名单文案: "目标受保护: ..."
    assert "受保护" in err["error"]


def test_sandbox_resolve_writable_false_does_NOT_block_protected_path(repo_root: Path):
    """writable=False (读路径) 仍不查黑名单 —— 锁死 read_file 不查 is_protected 的现状。
    这是 test_fs_tools.test_read_file_currently_does_not_block_agents_md 的姊妹断言,
    在 helper 层面再锁一遍以防有人改实现时偷偷加上。
    """
    target, err = _sandbox_resolve("AGENTS.md", writable=False)
    assert err is None
    assert target is not None


# ===========================================================================
# fs_tools.read_file: size 上限
# ===========================================================================


def test_read_file_rejects_oversized_file(repo_root: Path, monkeypatch: pytest.MonkeyPatch):
    """文件大小超过 MAX_READ_BYTES → ok=False 且带 size/limit 字段,
    防止 Agent 误读超大文件撑爆内存 / 拖慢推理。
    """
    # 用 monkeypatch 把阈值降到 10B, 避免构造 200KB 字符串拖慢测试
    monkeypatch.setattr(fs_tools, "MAX_READ_BYTES", 10)

    f = repo_root / "sandbox" / "big.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x" * 100, encoding="utf-8")

    out = read_file("sandbox/big.txt")
    assert out["ok"] is False
    assert "过大" in out["error"]
    assert out["size"] == 100
    assert out["limit"] == 10


def test_read_file_accepts_file_just_under_limit(repo_root: Path, monkeypatch: pytest.MonkeyPatch):
    """刚好等于阈值 (==limit) 仍应通过 —— 边界 off-by-one 防护。"""
    monkeypatch.setattr(fs_tools, "MAX_READ_BYTES", 10)
    f = repo_root / "sandbox" / "small.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x" * 10, encoding="utf-8")

    out = read_file("sandbox/small.txt")
    assert out["ok"] is True
    assert out["size"] == 10


def test_read_file_size_limit_constant_is_sane():
    """sanity: 默认 MAX_READ_BYTES 应在合理范围 (10KB ~ 10MB)。
    防有人误改成 0 (所有读都失败) 或 1GB (失去防御意义)。
    """
    assert 10_000 <= MAX_READ_BYTES <= 10_000_000


# ===========================================================================
# fs_tools.write_file: type 校验 + size 上限
# ===========================================================================


def test_write_file_rejects_non_string_content(repo_root: Path):
    """content 不是 str (e.g. int / None / dict) → ok=False, 类型名出现在 error 中。

    旧实现: 传给 Path.write_text 会抛 AttributeError, 经黑名单转 ok=False
            但 error 文案是 "AttributeError: ..." 对 LLM 不友好。
    新实现: 显式检查类型, 给清晰文案。
    """
    # 用 Any 强转绕过静态检查, 模拟 LLM 传错类型
    out = write_file("sandbox/note.txt", 12345)  # type: ignore[arg-type]
    assert out["ok"] is False
    assert "必须是字符串" in out["error"]
    assert "int" in out["error"]


def test_write_file_rejects_oversized_content(repo_root: Path, monkeypatch: pytest.MonkeyPatch):
    """content 长度超过 MAX_WRITE_BYTES → ok=False 且带 size/limit 字段。"""
    monkeypatch.setattr(fs_tools, "MAX_WRITE_BYTES", 10)

    out = write_file("sandbox/big.txt", "x" * 100)
    assert out["ok"] is False
    assert "过大" in out["error"]
    assert out["size"] == 100
    assert out["limit"] == 10


def test_write_file_happy_path_unchanged(repo_root: Path, monkeypatch: pytest.MonkeyPatch):
    """正常 write 行为保持: 写完后 read 拿回原内容, 大小字段正确。"""
    monkeypatch.setattr(fs_tools, "MAX_WRITE_BYTES", 1_000_000)
    out = write_file("sandbox/note.txt", "hello\nworld\n")
    assert out["ok"] is True
    assert out["path"] == "sandbox/note.txt"
    assert out["size"] == len("hello\nworld\n")
    # 文件确实写到了磁盘
    on_disk = (repo_root / "sandbox" / "note.txt").read_text(encoding="utf-8")
    assert on_disk == "hello\nworld\n"


def test_write_file_size_limit_constant_is_sane():
    """sanity: 默认 MAX_WRITE_BYTES 应 >= MAX_READ_BYTES (写允许比读大)。
    防有人误改成 0 或比读还小。
    """
    assert MAX_WRITE_BYTES >= MAX_READ_BYTES
    assert 10_000 <= MAX_WRITE_BYTES <= 100_000_000


def test_write_file_still_blocks_protected_agents_md(repo_root: Path):
    """黑名单路径仍被拒 —— 重构 _sandbox_resolve(writable=True) 后不能漏掉这层。"""
    out = write_file("AGENTS.md", "evil overwrite attempt")
    assert out["ok"] is False
    assert "受保护" in out["error"]


# ===========================================================================
# registry._safe_call helper
# ===========================================================================


def test_safe_call_returns_handler_result_on_success():
    """handler 正常返回 → _safe_call 透传, 不动 ok 字段。"""

    def h(x: int) -> dict[str, Any]:
        return {"ok": True, "x": x * 2}

    out = _safe_call(h, {"x": 5})
    assert out == {"ok": True, "x": 10}


def test_safe_call_swallows_runtime_error_with_error_envelope():
    """handler 抛 RuntimeError → {"ok": False, "error": "RuntimeError: ..."}
    与旧实现 run() 内部 try/except 形状一致 —— 见 test_registry 中
    test_run_handler_exception_is_swallowed_with_error_envelope 的契约。
    """

    def h(**_) -> dict[str, Any]:
        raise RuntimeError("kaboom")

    out = _safe_call(h, {})
    assert out["ok"] is False
    assert "RuntimeError" in out["error"]
    assert "kaboom" in out["error"]


def test_safe_call_swallows_value_error_with_type_name():
    """不同异常类型都应被吞 —— TypeError / ValueError / KeyError 同样走同条路径。"""

    def h(**_) -> dict[str, Any]:
        raise ValueError("bad input")

    out = _safe_call(h, {})
    assert out["ok"] is False
    assert "ValueError" in out["error"]
    assert "bad input" in out["error"]


def test_safe_call_runs_through_registry_run_in_low_risk(repo_root: Path):
    """端到端: registry.run() 调 _safe_call, handler raise 时仍按统一契约返回。"""

    def h(**_) -> dict[str, Any]:
        raise KeyError("missing thing")

    r = ToolRegistry()
    r.register(ToolDef(name="fail", description="", input_schema={}, risk="low", handler=h))
    out = r.run("fail", {})
    assert out["ok"] is False
    assert "KeyError" in out["error"]
    assert "missing thing" in out["error"]


# ===========================================================================
# memory_tools: type hint 不破坏 + 返回形状保持
# ===========================================================================


def test_memory_save_returns_id_field(repo_root: Path):
    """返回字典必须有 ok=True + id=int, 这是 LLM-facing 接口契约。"""
    out = memory_tools.memory_save(category="refactor", content="tools 层小修")
    assert out["ok"] is True
    assert isinstance(out["id"], int)
    assert out["id"] > 0


def test_memory_save_id_is_incrementally_unique(repo_root: Path):
    """连续写两条, id 应不同 (manager 自动递增)。"""
    a = memory_tools.memory_save(category="refactor", content="first")
    b = memory_tools.memory_save(category="refactor", content="second")
    assert a["id"] != b["id"]
    assert b["id"] > a["id"]