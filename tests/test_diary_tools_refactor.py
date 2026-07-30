"""锁定 diary_tools 的重构契约 (2026-07-30 round)。

本次重构包含三件事, 都是 *行为变更*:

1. ``_format_block`` 抽出来 (块格式漂移集中点)
2. ``diary_write`` OSError 兜底 (与 ``fs_tools`` 对齐: PermissionError / 磁盘满
   不再向上抛, 而是 ``ok=False`` + ``"写入失败: <type>: <msg>"``)
3. ``_fail(error)`` helper, 统一 ``ok=False`` 字典形态

测试目标: 把新契约固定, 防止后续误改把 OSError 兜底丢掉 (fs_tools 已经踩过一次
类似的坑, 这次先补上测试再写代码)。

注意: ``test_diary_archive_passes_through_to_auto_archive`` 是仓库历史缺失
``diary_archive`` 的预存 bug, 与本次重构无关, 这里不动它。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from xragent.tools import diary_tools
from xragent.tools.diary_tools import _fail, _format_block, _require_nonblank, diary_write


# ---------- _fail / _require_nonblank: helper 层 ----------


def test_fail_returns_ok_false_with_error():
    """``_fail`` 与 ``fs_tools._fail`` 同形: ``ok=False`` + ``error`` 字符串。

    这是 LLM 工具层契约的核心 (失败永远返回 dict, 不抛), 任何 helper 重构
    都不能破坏。
    """
    out = _fail("something went wrong")
    assert out == {"ok": False, "error": "something went wrong"}
    # 不允许出现 ``ok`` 之外的 ok-true-ish 字段 (防止 helper 误把 path 也塞进去)
    assert set(out.keys()) == {"ok", "error"}


def test_require_nonblank_returns_none_when_valid():
    """合法字符串 → ``None`` (表示通过)。"""
    assert _require_nonblank("title", "hello") is None
    assert _require_nonblank("body", "  x  ") is None  # 中间有非空白字符即合法


def test_require_nonblank_returns_error_string_when_invalid():
    """非法值 → 错误字符串 (不是 ``None``, 不是 raise)。"""
    # 类型错
    err_type = _require_nonblank("title", 42)
    assert err_type is not None
    assert "title" in err_type and "int" in err_type
    # 空白
    err_blank = _require_nonblank("body", "   \n\t  ")
    assert err_blank is not None
    assert "body" in err_blank and "不能为空" in err_blank


# ---------- _format_block: 块格式漂移锁定 ----------


def test_format_block_assembles_canonical_shape():
    """标准输入 → ``\\n## [ts] title\\n\\nbody\\n`` (与既有文件格式完全一致)。

    这条锁的是 *byte-level* 格式, 防止有人手贱改成 ``## ts - title`` /
    去掉尾部换行 / 改 body 前缀, 那样会让旧 diary 文件和新 diary 文件的
    block 头看起来不是同一个程序写的。
    """
    out = _format_block("14:32:07", "Turn1", "hello world")
    assert out == "\n## [14:32:07] Turn1\n\nhello world\n"


def test_format_block_strips_trailing_newlines_from_body():
    """body 末尾无论多少个换行 / 空格都被 ``rstrip`` 吃成单个 ``\\n``。"""
    out = _format_block("00:00:00", "t", "line1\nline2\n\n\n\n   ")
    assert out.endswith("line2\n"), f"尾部换行没收干净: {out!r}"
    # 不应出现连续两个 \\n (那意味着 rstrip 没起作用)
    assert "\n\n\n" not in out


def test_format_block_preserves_body_internal_newlines():
    """body 内部的 ``\\n`` 不会被吃掉 (只吃尾部空白)。"""
    out = _format_block("00:00:00", "t", "a\nb\nc\n\n\n")
    assert "a\nb\nc" in out
    # 内部 a/b/c 之间的单换行保留
    assert "a\nb" in out and "b\nc" in out


# ---------- diary_write: OSError 兜底 ----------


def test_diary_write_returns_ok_false_when_open_raises_oserror(repo_root, monkeypatch):
    """``target.open`` 抛 PermissionError → ``ok=False`` + error 含 ``"写入失败"``。

    跟 ``test_fs_tools_oserror.py`` 同一套路: monkeypatch ``Path.open`` 让它
    抛 OSError, 不依赖真实文件系统权限 (macOS SIP / root 才能 chmod 的痛点)。
    """
    real_open = Path.open

    def boom(self, *args, **kwargs):  # noqa: ARG001
        # 只对 diary 路径抛错, 避免 conftest 里的 git open 也被炸
        if "diary" in str(self):
            raise PermissionError(13, "Read-only file system", str(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", boom)

    r = diary_write("Turn1", "body")
    assert r["ok"] is False
    assert "写入失败" in r["error"]
    assert "PermissionError" in r["error"]
    assert "Read-only file system" in r["error"]


def test_diary_write_returns_ok_false_when_write_raises_oserror(repo_root, monkeypatch):
    """``f.write`` 抛 OSError (磁盘满) → ``ok=False`` + ``"写入失败"``。

    与 open 抛错同路径, 但走的是 *write 阶段* 抛错。open 成功不代表 write
    也成功 (例如磁盘配额满 / 配额到顶), 所以要单独锁。
    """
    def fake_open_write_only_oserror(self, mode="r", *args, **kwargs):  # noqa: ARG001
        if "diary" in str(self):
            # 模拟 open 成功但 write 失败: 返回一个写入会抛错的 file-like
            class _BoomFile:
                def __enter__(self_inner):  # noqa: N805
                    return self_inner
                def __exit__(self_inner, *exc):  # noqa: N805
                    return False
                def write(self_inner, _data):  # noqa: N805
                    raise OSError(28, "No space left on device", str(self))
            return _BoomFile()
        return Path.open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fake_open_write_only_oserror)

    r = diary_write("Turn1", "body")
    assert r["ok"] is False
    assert "写入失败" in r["error"]
    assert "OSError" in r["error"]
    assert "No space left" in r["error"]


def test_diary_write_oserror_does_not_create_empty_file(repo_root, monkeypatch):
    """OSError 时不应在 diary/ 下留下空文件 (写一半的 0 字节文件)。

    跟 ``test_diary_write_validation_failure_does_not_touch_existing_file``
    同精神: 任何失败路径都不能污染文件系统。
    """
    def boom(self, *args, **kwargs):  # noqa: ARG001
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "open", boom)

    day = time.strftime("%Y-%m-%d")
    expected = repo_root / "diary" / f"{day}.md"
    assert not expected.exists()

    r = diary_write("Turn1", "body")
    assert r["ok"] is False
    # 失败后不应出现新文件
    assert not expected.exists(), f"OSError 后竟然留下了文件: {expected}"


# ---------- diary_write: 回归 ----------


def test_diary_write_happy_path_still_returns_posix_relative_path(repo_root):
    """加 OSError 兜底后, 正常路径不能被吃掉 (跟 ``test_fs_tools_oserror`` 末尾同模式)。"""
    r = diary_write("happy", "ok-body")
    assert r["ok"] is True
    assert r["path"].startswith("diary/")
    assert "\\" not in r["path"]
    assert r["path"].endswith(".md")
    # 实际文件存在且内容含 ``## [`` 块头 (证明走的还是 ``_format_block``)
    p = repo_root / r["path"]
    assert p.exists()
    assert "## [" in p.read_text(encoding="utf-8")


def test_module_exports_required_symbols():
    """``diary_tools`` 模块对外符号不丢: ``diary_write`` 必须可被 import。

    ``diary_archive`` 是仓库历史预存 bug (缺失), 不在本测试覆盖范围;
    这里只锁 ``diary_write`` (本次重构的目标)。
    """
    assert hasattr(diary_tools, "diary_write")
    assert callable(diary_tools.diary_write)
    # 抽出的 helper 不必对外导出, 但模块级能用
    assert callable(diary_tools._format_block)
    assert callable(diary_tools._fail)
    assert callable(diary_tools._require_nonblank)