"""git_tools.git_push output_tail_chars 行为 (v0.5.6 新增)。

为什么独立文件:
  - 与 test_git_tools.py (契约锁) / test_git_tools_timeout.py (timeout)
    分离,本文件只覆盖 *输出截断* 行为。
  - 复用的 monkeypatch 模式与 test_git_tools_timeout.py 相同: 替换
    ``xragent.tools.git_tools.subprocess.run`` 截到调用, 不真跑 git。

设计要点 (跟 exec_tools._truncate_output 对齐):
  - 默认 4000 字, 与 exec_tools.OUTPUT_TAIL_LIMIT 一致。
  - 短输入 (<= tail_chars) 原样透传, 不插 OMITTED_MARKER。
  - 长输入 + head_chars=0 → 直接 ``text[-tail:]`` (无 marker, 因我们只
    关心尾部最新错误; 截断本身由 msg 长度等于 tail_chars 体现)。
  - 兜底矩阵: None / bool / 非数值 / <=0 一律回落到默认 4000。
  - 不用 time.sleep: 全靠 fake_run 即时返回。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from xragent.tools import git_tools


# ===========================================================================
# 默认值 + 常量稳定
# ===========================================================================


def test_default_push_output_tail_chars_constant_is_4000():
    """DEFAULT_PUSH_OUTPUT_TAIL_CHARS 必须 == 4000 (= exec_tools.OUTPUT_TAIL_LIMIT)。"""
    from xragent.tools.exec_tools import OUTPUT_TAIL_LIMIT

    assert git_tools.DEFAULT_PUSH_OUTPUT_TAIL_CHARS == 4000
    assert git_tools.DEFAULT_PUSH_OUTPUT_TAIL_CHARS == OUTPUT_TAIL_LIMIT


# ===========================================================================
# 默认值路径: 不传 output_tail_chars → 回落 4000
# ===========================================================================


def test_git_push_default_truncates_long_stderr_to_4000(repo_root: Path):
    """不传 output_tail_chars → 长 stderr 被截到 4000 字 (head_chars=0 → 无 marker)。

    验证 *真的进了* _truncate_output, 而不是直接 .strip() 拼回去。
    head_chars=0 时 _truncate_output 返回 ``text[-tail:]``, 不插 marker。
    """
    long_stderr = "x" * 8000  # 8000 字符, 远超 4000

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=128, stderr=long_stderr, stdout=""
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push()
    finally:
        monkey.undo()

    assert r["ok"] is False
    # 关键: msg 长度 == 4000 (被截了), 不是 8000
    assert len(r["msg"]) == 4000, (
        f"长 stderr 应被截到 4000, 实际 len={len(r['msg'])}"
    )
    # head_chars=0 → 无 OMITTED_MARKER (设计: 只关心尾部)
    assert "...[省略" not in r["msg"]
    # 内容: 末尾 4000 字全是 "x"
    assert r["msg"] == "x" * 4000


# ===========================================================================
# 短输出: 原样透传, 不截
# ===========================================================================


def test_git_push_short_output_passes_through_untruncated(repo_root: Path):
    """短 stderr (<= 4000) → msg 原样透传, 不截。"""
    short_stderr = "fatal: repository 'origin' does not exist"

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=128, stderr=short_stderr, stdout=""
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push()
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert r["msg"] == short_stderr
    assert len(r["msg"]) == len(short_stderr)
    assert "...[省略" not in r["msg"]


def test_git_push_short_output_with_surrounding_whitespace_is_stripped(
    repo_root: Path,
):
    """stderr 带前后空白 → 先 strip 再截断 (短消息保留全部内容)。"""
    raw = "  \n  fatal: bad ref  \n  "

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=128, stderr=raw, stdout=""
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push()
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert r["msg"] == "fatal: bad ref"
    assert "...[省略" not in r["msg"]


def test_git_push_exactly_at_boundary_not_truncated(repo_root: Path):
    """stderr 长度恰好 == tail_chars (4000) → 不截, 等号边界包含在透传侧。"""
    boundary = "y" * 4000

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=1, stderr=boundary, stdout=""
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push()
    finally:
        monkey.undo()

    assert len(r["msg"]) == 4000
    assert r["msg"] == boundary
    assert "...[省略" not in r["msg"]


# ===========================================================================
# 自定义 output_tail_chars
# ===========================================================================


def test_git_push_custom_output_tail_chars_truncates_to_that_size(
    repo_root: Path,
):
    """output_tail_chars=50 → 8000 字符 stderr 被截到 50 字 (无 marker, head=0)。"""
    long_stderr = "Y" * 8000

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=1, stderr=long_stderr, stdout=""
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push(output_tail_chars=50)
    finally:
        monkey.undo()

    assert r["ok"] is False
    # 关键: msg 长度 == 50
    assert len(r["msg"]) == 50, (
        f"output_tail_chars=50 应截到 50, 实际 len={len(r['msg'])}"
    )
    # 内容: 末尾 50 字全是 "Y" (head_chars=0 → 全是尾部)
    assert r["msg"] == "Y" * 50
    # head_chars=0 → 无 marker
    assert "...[省略" not in r["msg"]


def test_git_push_custom_output_tail_chars_passes_through_when_short(
    repo_root: Path,
):
    """output_tail_chars=1000 + stderr=500 字符 → 原样透传, 长度 = 500。"""
    short = "z" * 500

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=128, stderr=short, stdout=""
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push(output_tail_chars=1000)
    finally:
        monkey.undo()

    assert r["msg"] == short
    assert len(r["msg"]) == 500
    assert "...[省略" not in r["msg"]


def test_git_push_custom_output_tail_chars_one(repo_root: Path):
    """output_tail_chars=1 → 极端下限: 8000 字符 stderr 被截到 1 字。

    锁住 min_value=1 行为: tail_chars 必须 >= 1, 否则 _coerce_int 回落默认。
    这里 1 是合法值, 应该真截到 1 字。
    """
    long_stderr = "Z" * 8000

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=1, stderr=long_stderr, stdout=""
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push(output_tail_chars=1)
    finally:
        monkey.undo()

    assert len(r["msg"]) == 1
    assert r["msg"] == "Z"


# ===========================================================================
# 兜底矩阵: None / bool / 非数值 / <=0 → 默认 4000
# ===========================================================================


@pytest.mark.parametrize(
    "bad_value",
    [None, 0, -1, -100, True, False, "100", [100], {"x": 100}, 0.0],
    ids=[
        "None", "zero", "neg1", "neg100", "True", "False",
        "str-100", "list-100", "dict-100", "float-0",
    ],
)
def test_git_push_invalid_output_tail_chars_falls_back_to_default(
    repo_root: Path, bad_value
):
    """output_tail_chars 任何非法值 → 回落 4000, 长 stderr 被截到 4000 字。

    期望: 非法值 *不会* 触发 TypeError / ValueError 冒到 LLM 面前,
    也不会让 msg 保持 8000 字原长。
    """
    long_stderr = "A" * 8000

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=1, stderr=long_stderr, stdout=""
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push(output_tail_chars=bad_value)  # type: ignore[arg-type]
    finally:
        monkey.undo()

    # 回落 4000 → msg 长度必须 == 4000 (被截)
    assert len(r["msg"]) == 4000, (
        f"output_tail_chars={bad_value!r} 应回落 4000, 实际 len={len(r['msg'])}"
    )
    # 内容: 末尾 4000 字全是 "A" (head_chars=0)
    assert r["msg"] == "A" * 4000
    # head_chars=0 → 无 marker
    assert "...[省略" not in r["msg"]


# ===========================================================================
# stdout fallback 路径: stderr 空时走 stdout
# ===========================================================================


def test_git_push_falls_back_to_stdout_when_stderr_empty(repo_root: Path):
    """stderr 空 + stdout 有内容 (如 'Everything up-to-date') → msg 来自 stdout。

    stdout 长度 8000, output_tail_chars=100 → msg 长度 = 100。
    """
    long_stdout = "B" * 8000

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=0, stderr="", stdout=long_stdout
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push(output_tail_chars=100)
    finally:
        monkey.undo()

    assert r["ok"] is True
    assert len(r["msg"]) == 100
    assert r["msg"] == "B" * 100
    assert "...[省略" not in r["msg"]


def test_git_push_short_stdout_passes_through(repo_root: Path):
    """stderr 空 + stdout 短消息 → msg = stdout.strip(), 原样透传。"""
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=0, stderr="", stdout="Everything up-to-date"
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push()
    finally:
        monkey.undo()

    assert r == {"ok": True, "msg": "Everything up-to-date"}


# ===========================================================================
# 成功路径: msg 为空, 截断不爆
# ===========================================================================


def test_git_push_success_msg_empty_string_passes_through(repo_root: Path):
    """成功 push + stderr/stdout 都空 → msg="" (空串也走 _truncate_output 但 n=0)。"""
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stderr="", stdout="")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push()
    finally:
        monkey.undo()

    assert r == {"ok": True, "msg": ""}
    assert len(r["msg"]) == 0
    assert "...[省略" not in r["msg"]


# ===========================================================================
# 公共 helper 契约: _resolve_output_tail_chars 纯函数边界
# ===========================================================================


def test_resolve_output_tail_chars_default_used_when_none():
    assert git_tools._resolve_output_tail_chars(None) == 4000


def test_resolve_output_tail_chars_default_used_when_zero_or_negative():
    assert git_tools._resolve_output_tail_chars(0) == 4000
    assert git_tools._resolve_output_tail_chars(-5) == 4000
    assert git_tools._resolve_output_tail_chars(-0.5) == 4000


def test_resolve_output_tail_chars_default_used_when_non_numeric_types():
    assert git_tools._resolve_output_tail_chars("4000") == 4000
    assert git_tools._resolve_output_tail_chars([4000]) == 4000
    assert git_tools._resolve_output_tail_chars({"x": 4000}) == 4000


def test_resolve_output_tail_chars_bool_rejected_even_though_int_subclass():
    """bool 是 int 子类, 显式拒绝, 与 _resolve_timeout 行为一致。"""
    assert git_tools._resolve_output_tail_chars(True) == 4000
    assert git_tools._resolve_output_tail_chars(False) == 4000


def test_resolve_output_tail_chars_passes_through_positive_int():
    assert git_tools._resolve_output_tail_chars(100) == 100
    assert git_tools._resolve_output_tail_chars(10000) == 10000


def test_resolve_output_tail_chars_passes_through_positive_float_int_truncation():
    """float → int() 截断, 与 _coerce_int 行为一致。"""
    assert git_tools._resolve_output_tail_chars(100.7) == 100


def test_resolve_output_tail_chars_min_value_is_one():
    """边界: 1 是合法最小值, 不应被回落。"""
    assert git_tools._resolve_output_tail_chars(1) == 1


# ===========================================================================
# Signature 暴露: registry input_schema 依赖这个 kw-only
# ===========================================================================


def test_git_push_signature_exposes_output_tail_chars_keyword():
    """inspect.signature 应暴露 output_tail_chars 形参, 默认 = DEFAULT_PUSH_OUTPUT_TAIL_CHARS。

    registry input_schema 用 inspect 抽默认值; 一旦漂移 LLM 拿到的 default
    会跟实际不符。
    """
    import inspect

    sig = inspect.signature(git_tools.git_push)
    assert "output_tail_chars" in sig.parameters
    p = sig.parameters["output_tail_chars"]
    # kw-only (def 里 ``*,`` 之后)
    assert p.kind is inspect.Parameter.KEYWORD_ONLY, (
        f"output_tail_chars 应为 kw-only, 实际 kind={p.kind}"
    )
    assert p.default == git_tools.DEFAULT_PUSH_OUTPUT_TAIL_CHARS


# ===========================================================================
# 不变量: return dict 仍只含
def test_git_push_return_dict_has_exactly_ok_and_msg(repo_root: Path):
    """长 stderr 截断后, 返回 dict 仍只含 {ok, msg} 两个键 —— 不引入幻键。"""
    long_stderr = 'x' * 8000

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=128, stderr=long_stderr, stdout=''
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, 'run', fake_run)
    try:
        r = git_tools.git_push(output_tail_chars=100)
    finally:
        monkey.undo()

    assert set(r.keys()) == {'ok', 'msg'}, (
        f'返回键集合漂移: {sorted(r.keys())}'
    )
    assert len(r['msg']) == 100


def test_git_push_return_dict_shape_for_success_path(repo_root: Path):
    """成功路径: dict 仍只有 ok + msg 两个键。"""
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stderr='', stdout='')

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, 'run', fake_run)
    try:
        r = git_tools.git_push()
    finally:
        monkey.undo()

    assert set(r.keys()) == {'ok', 'msg'}

