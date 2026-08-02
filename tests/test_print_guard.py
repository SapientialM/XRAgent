"""tests/test_print_guard.py — 锁 print_guard API + 与 main.py 集成。

任务背景：v0.4 refactor 把 ``cmd_autonomous`` 里 3 处重复的
``try: ... except Exception as e: print(f"[autonomous] <X> failed: {e}", flush=True)``
模板抽到 ``util.print_guard.print_guard``。本测试锁:

  1. 成功路径直接返回 ``fn()`` 的值（透传，不包、不改）
  2. 失败路径返回 ``None``（强制；不返回 fallback，让 caller 显式判断）
  3. 失败时 print ``[prefix] {label} failed: {e}`` 到 stdout
  4. prefix 可定制（默认 ``"autonomous"``，但调用方能改）
  5. 任意 ``Exception`` 子类都被吞（不只 ``OSError``）
  6. fn 返回 ``None`` 是合法业务值，guard 不该误判成失败
"""
from __future__ import annotations

import pytest

from xragent.util.print_guard import print_guard


# ------------------------------------------------------------------ success path


def test_returns_fn_value_on_success():
    """fn 正常返回 → guard 原样透传，不包不剥。"""

    def fn() -> int:
        return 42

    assert print_guard("op", fn) == 42


def test_returns_fn_tuple_on_success():
    """fn 返回 tuple 也透传（push 路径返 ``(ok, msg)``）。"""

    def fn() -> tuple[bool, str]:
        return (True, "all good")

    assert print_guard("push", fn) == (True, "all good")


def test_does_not_print_on_success(capsys: pytest.CaptureFixture[str]) -> None:
    """成功时不该 print 任何东西（fail-only helper）。"""
    print_guard("op", lambda: 1)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# ------------------------------------------------------------------ failure path


def test_returns_none_on_exception():
    """fn 抛 Exception → guard 返回 ``None``。"""

    def boom() -> int:
        raise ValueError("nope")

    assert print_guard("op", boom) is None


def test_returns_none_on_oserror():
    """``OSError`` 也吞（commit / push 路径常见）。"""

    def boom() -> int:
        raise OSError("disk full")

    assert print_guard("commit", boom) is None


def test_returns_none_on_runtime_error():
    """``RuntimeError`` 也吞（task gen 路径常见）。"""

    def boom() -> int:
        raise RuntimeError("queue underflow")

    assert print_guard("task gen", boom) is None


def test_prints_failure_with_default_prefix(capsys: pytest.CaptureFixture[str]) -> None:
    """失败时 print ``[autonomous] {label} failed: {e}``。"""

    def boom() -> int:
        raise ValueError("kaboom")

    print_guard("push", boom)
    captured = capsys.readouterr()
    assert captured.out == "[autonomous] push failed: kaboom\n"
    assert captured.err == ""


def test_prints_failure_with_custom_prefix(capsys: pytest.CaptureFixture[str]) -> None:
    """``prefix`` kwarg 生效：调用方能换 context。"""

    def boom() -> int:
        raise ValueError("kaboom")

    print_guard("task gen", boom, prefix="supervised")
    captured = capsys.readouterr()
    assert captured.out == "[supervised] task gen failed: kaboom\n"


def test_does_not_swallow_keyboard_interrupt():
    """``KeyboardInterrupt`` 是 ``BaseException`` 不 ``Exception``，应让 caller 收到。
    否则 SIGTERM 之类 ctrl-c 时 autonomous 进程会被吞掉。
    """

    def boom() -> int:
        raise KeyboardInterrupt("user ctrl-c")

    with pytest.raises(KeyboardInterrupt):
        print_guard("op", boom)


def test_does_not_swallow_system_exit():
    """``SystemExit`` 也是 ``BaseException``，透传。"""

    def boom() -> int:
        raise SystemExit(1)

    with pytest.raises(SystemExit):
        print_guard("op", boom)


# ------------------------------------------------------------------ None as valid value


def test_fn_returning_none_is_not_treated_as_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """fn 返回 ``None`` 是合法业务值（不是 guard 兜的），不应 print。

    调用方区分"fn 真返回 None"vs"guard 兜的 None"的方式：靠业务语义而非返回值
    类型——例如 task gen 的 fallback 是 sleep 60s 而非把 None 当有效 prompt 喂进 loop。
    """
    print_guard("op", lambda: None)
    captured = capsys.readouterr()
    assert captured.out == ""  # no print


def test_fn_returning_false_is_not_treated_as_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """fn 返 ``False``（push 失败）属合法业务值，不应被 guard 当成异常。"""

    def fake_push() -> bool:
        return False

    assert print_guard("push", fake_push) is False
    captured = capsys.readouterr()
    assert captured.out == ""


# ------------------------------------------------------------------ integration smoke


def test_integration_push_style():
    """模拟 push 路径：fn 内部调 sg.push() 抛异常 → guard 返回 None。"""

    def fake_push() -> bool:
        raise OSError("network unreachable")

    result = print_guard("push", fake_push)
    # caller 看到 None → 不更新 last_push_ts
    assert result is None


def test_integration_commit_style():
    """模拟 commit 路径：fn 抛 → caller 不调 record_done。"""

    def fake_commit() -> str | None:
        raise OSError("git index locked")

    result = print_guard("commit", fake_commit)
    assert result is None