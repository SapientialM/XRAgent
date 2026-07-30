"""统一 ``ok=False`` 字典工厂 (LLM 工具契约)。

为什么存在
----------
四个工具模块 (fs_tools / diary_tools / exec_tools / git_tools) 都需要
在异常路径返回一个 ``{"ok": False, ...}`` 字典,而不是抛异常 ——
这是 LLM 工具调用层的硬契约 ("always returns dict")。每个模块各自
inline 写一个 ``_fail`` 工厂,字段名 (``error`` vs ``msg``) 和是否
支持 ``**extras`` 略不一样,导致 4 处漂移。

集中到这里后:
  * 调用方仍然用 ``_fail(...)`` 这个**模块私有名字**,没有破坏
    ``fs_tools._fail`` / ``exec_tools._fail`` 等已有测试 pin 死的访问路径;
    具体绑定在 4 个工具模块顶部 ``from .util.result import fail_X as _fail``
  * 字段命名差异 (``error`` vs ``msg``) 用两个独立函数表达,不强行
    抽象成 ``fail(field=..., message=...)`` 之类的运行时参数(那会让
    git_push 的 LLM 契约从编译期锁变成运行时拼,反而退步)

字段命名约定的来源
------------------
  * ``fail_error`` 用 ``error`` 字段:read_file / list_dir / write_file /
    diary_write / run_cmd 这些失败诊断里都是 ``"读取失败: ..."`` /
    ``"写入失败: ..."`` / ``"命令被拦截: ..."``,语义就是 "出错文案",
    用 ``error`` 是直觉;test_exec_tools.py 里
    ``assert set(r.keys()) == {"ok", "error"}`` 已经锁死这个键集合。
  * ``fail_msg`` 用 ``msg`` 字段:git_push 已经在契约里固定
    ``{"ok": bool, "msg": str}`` (成功为空、失败为 stderr),test_git_tools.py
    里 ``assert r == {"ok": True, "msg": ""}`` 锁死,改成 ``error`` 会触发
    一连串契约回归。把它的错误路径也用 ``msg`` 就和成功路径对齐。

``**extras`` 是 positional-only 之后的关键字透传
----------------------------------------------
LLM 契约要求"最小键集合"——成功路径只暴露规定的字段,失败路径也不
能随便塞新键。所以 extras 必须**显式传入才出现**,不在工厂内部硬编码
任何额外键 (例如 ``cmd`` / ``returncode`` / ``timeout``)。调用方根据
具体失败类型决定要不要带 ``timeout=True`` / ``stdout=...`` 之类的旗标,
工厂只负责把它们原样合并进字典。
"""
from __future__ import annotations

from typing import Any


def fail_error(error: str, /, **extras: Any) -> dict[str, Any]:
    """``ok=False`` 字典工厂,失败文案走 ``error`` 字段。

    Args:
        error: 失败诊断字符串;positional-only,所以调用方不能写成
            ``_fail(error="...")``——必须位置参数。
        **extras: 调用方根据失败类型显式附加的字段 (例如
            ``timeout=True`` / ``stdout=...`` / ``stderr=...``)。
            不传则不出现,默认键集合严格只有 ``{"ok", "error"}``。

    Returns:
        ``{"ok": False, "error": error, **extras}``。LLM 看到 ``ok=False``
        后读 ``error`` (或 ``msg`` 同源字段) 取诊断;extras 视调用方约定。
    """
    out: dict[str, Any] = {"ok": False, "error": error}
    out.update(extras)
    return out


def fail_msg(msg: str, /, **extras: Any) -> dict[str, Any]:
    """``ok=False`` 字典工厂,失败文案走 ``msg`` 字段。

    与 :func:`fail_error` 同形态,仅字段名不同;服务于 git_push 这类
    成功 / 失败都用 ``msg`` 字段表达的契约。

    Args:
        msg: 失败诊断字符串;positional-only。
        **extras: 调用方显式附加字段;不传则不出现。
            git_push 的超时分支传 ``timed_out=True``,test_git_tools_timeout.py
            ``test_fail_extras_are_added_only_when_provided`` 锁这一契约。

    Returns:
        ``{"ok": False, "msg": msg, **extras}``。
    """
    out: dict[str, Any] = {"ok": False, "msg": msg}
    out.update(extras)
    return out


__all__ = ["fail_error", "fail_msg"]