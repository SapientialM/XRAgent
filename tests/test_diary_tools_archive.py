"""``tools.diary_tools.diary_archive`` 包装器契约测试。

``util/diary_archive.py`` 核心逻辑已在 ``tests/test_diary_archive.py``
覆盖; 本文件只锁 wrapper 层的契约 — 这是 LLM 工具层唯一入口, 三个断言
同时验证三件事:

  1. wrapper 路径源唯一 (``settings.diary_dir``), 不接受外部参数 —
     防止有人为了"方便"加 ``diary_dir=...`` 参数破坏单一真相源。
  2. 参数校验 (``weeks_threshold`` 类型 / 非负) — 与 ``diary_write``
     工具层契约对齐 (校验失败 → ``ok=False`` 不抛异常)。
  3. OSError 兜底 — 底层 ``auto_archive`` 异常时返回 ``ok=False``
     而不破坏 LLM 工具层 "always returns dict" 契约。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from xragent.config.settings import get_settings
from xragent.tools import diary_tools


def test_diary_archive_uses_settings_diary_dir(repo_root, monkeypatch):
    """spy ``auto_archive``, 验证 wrapper 传给它的就是 ``settings.diary_dir``。"""
    calls: list[tuple] = []

    def spy(diary_dir, weeks_threshold=2):
        calls.append((diary_dir, weeks_threshold))
        return {"ok": True, "archived": [], "skipped": []}

    monkeypatch.setattr(diary_tools, "auto_archive", spy)

    r = diary_tools.diary_archive(weeks_threshold=3)

    assert r["ok"] is True
    assert len(calls) == 1, f"应调一次 auto_archive，实际 {len(calls)} 次"
    diary_dir_arg, threshold_arg = calls[0]
    assert Path(diary_dir_arg) == get_settings().diary_dir
    assert threshold_arg == 3


def test_diary_archive_default_threshold_is_two(repo_root, monkeypatch):
    """``weeks_threshold`` 默认 2 — 与 ``util.auto_archive`` 默认对齐。"""
    seen: list[int] = []

    def spy(diary_dir, weeks_threshold=2):
        seen.append(weeks_threshold)
        return {"ok": True, "archived": [], "skipped": []}

    monkeypatch.setattr(diary_tools, "auto_archive", spy)

    diary_tools.diary_archive()

    assert seen == [2]


@pytest.mark.parametrize(
    "bad, label",
    [
        ("2", "字符串"),
        (2.0, "浮点数"),
        (True, "bool (int 子类)"),
        (-1, "负数"),
    ],
)
def test_diary_archive_rejects_bad_threshold(bad, label, monkeypatch):
    """``weeks_threshold`` 校验失败应返回 ``ok=False`` 且不调底层。"""
    spy_called = []

    def spy(diary_dir, weeks_threshold=2):
        spy_called.append(True)
        return {"ok": True, "archived": [], "skipped": []}

    monkeypatch.setattr(diary_tools, "auto_archive", spy)

    r = diary_tools.diary_archive(weeks_threshold=bad)

    assert r["ok"] is False, f"{label} 应被拒，实际 {r!r}"
    assert "error" in r
    assert spy_called == [], f"{label} 应在底层被调前返回，实际调了 {len(spy_called)} 次"


def test_diary_archive_swallows_oserror(repo_root, monkeypatch):
    """``auto_archive`` 抛 ``OSError`` 时 wrapper 返回 ``ok=False`` 不上抛。"""
    def boom(diary_dir, weeks_threshold=2):
        raise OSError("disk full")

    monkeypatch.setattr(diary_tools, "auto_archive", boom)

    r = diary_tools.diary_archive()
    assert r["ok"] is False
    assert "error" in r
    assert "OSError" in r["error"]
    assert "disk full" in r["error"]