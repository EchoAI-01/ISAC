"""日志上下文贯穿 (可观测性增强)。

基于 structlog 的 contextvars 机制,把 trace_id / session_id / agent_id 等
关联字段绑定到当前异步上下文;`logger.py` 已在处理器链装配
``structlog.contextvars.merge_contextvars`` (见 logger.py),因此绑定后
这些字段会自动出现在其后每一条日志里,无需在每个 ``logger.xxx()`` 调用处手传。

设计约束:
- 绑定/清理失败绝不冒泡到主链路 —— 日志是旁路信号,不能因它中断消息处理。
- ``None`` 值字段被忽略,避免污染上下文 (例如 agent_id 尚未确定时)。
- structlog 不可用时整体降级为 no-op,保证框架可导入、可运行。
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

try:
    import structlog

    _HAS_STRUCTLOG = True
except ImportError:  # pragma: no cover
    _HAS_STRUCTLOG = False


@contextlib.contextmanager
def bind_log_context(**fields: Any) -> Iterator[None]:
    """在 ``with`` 作用域内把字段绑定到日志上下文,退出时精确还原。

    嵌套安全:内层退出后恢复外层的值 (基于 bind 返回的 token reset),
    而不是把字段整体清空。

    用法::

        with bind_log_context(trace_id=tid, session_id=sid, agent_id=aid):
            ...  # 期间所有日志自动带上这三个字段
    """
    clean = {key: value for key, value in fields.items() if value is not None}
    if not _HAS_STRUCTLOG or not clean:
        yield
        return
    try:
        tokens = structlog.contextvars.bind_contextvars(**clean)
    except Exception:  # noqa: BLE001 - 绑定失败不得影响主链路
        yield
        return
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            structlog.contextvars.reset_contextvars(**tokens)


def clear_log_context() -> None:
    """清空当前日志上下文的全部绑定字段 (进程/任务边界收尾时使用)。"""
    if _HAS_STRUCTLOG:
        with contextlib.suppress(Exception):
            structlog.contextvars.clear_contextvars()


def get_log_context() -> dict[str, Any]:
    """返回当前已绑定的日志上下文字段 (只读快照,主要供测试与诊断)。"""
    if not _HAS_STRUCTLOG:
        return {}
    try:
        return dict(structlog.contextvars.get_contextvars())
    except Exception:  # noqa: BLE001
        return {}
