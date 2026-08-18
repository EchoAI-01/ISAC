"""EventBus: Intercept + Async 双层事件总线 (ARCHITECTURE.md 二)。

- Intercept 链: 按优先级串行执行，处理器返回 None 则阻止后续并中断流程
- Async 处理器: 并发执行，异常隔离，不影响主流程
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from isac.core.events import EventType
from isac.utils.logger import get_logger

logger = get_logger(__name__)

InterceptHandler = Callable[[Any], Awaitable[Any]]
AsyncHandler = Callable[[Any], Awaitable[None]]


class EventBus:
    """双层事件总线。"""

    def __init__(self) -> None:
        self._intercept: dict[EventType, list[tuple[int, InterceptHandler]]] = {}
        self._async: dict[EventType, list[AsyncHandler]] = {}
        # N5b 批次C C2: 与 _intercept/_async 同索引的来源列表, 供按来源 deregister。
        self._intercept_sources: dict[EventType, list[str]] = {}
        self._async_sources: dict[EventType, list[str]] = {}
        # on_load 期间设置的默认来源 (激活模块 set_current_source(plugin_name))。
        self._current_source: str | None = None

    def on_intercept(
        self,
        event: EventType,
        handler: InterceptHandler,
        priority: int = 0,
        *,
        source: str | None = None,
    ) -> None:
        """注册 Intercept 处理器。priority 越大越先执行。"""
        self._intercept.setdefault(event, []).append((priority, handler))
        self._intercept_sources.setdefault(event, []).append(source or self._current_source or "builtin")

    def on_async(self, event: EventType, handler: AsyncHandler, *, source: str | None = None) -> None:
        """注册 Async 处理器（并发执行）。"""
        self._async.setdefault(event, []).append(handler)
        self._async_sources.setdefault(event, []).append(source or self._current_source or "builtin")

    def set_current_source(self, source: str | None) -> None:
        """设置后续 on_intercept/on_async 的默认来源 (on_load 期间设为插件名, 结束后置 None)。"""
        self._current_source = source

    def deregister_by_source(self, source: str) -> int:
        """移除指定来源的全部处理器 (intercept + async), 返回被移除数量 (C2 热重载同步)。"""
        removed = 0
        for ev in list(self._intercept.keys()):
            removed += _filter_by_source(self._intercept, self._intercept_sources, ev, source)
        for ev in list(self._async.keys()):
            removed += _filter_by_source(self._async, self._async_sources, ev, source)
        return removed

    async def fire_intercept(self, event: EventType, payload: Any) -> Any | None:
        """按优先级串行执行 Intercept 链。

        处理器可修改并返回 payload；返回 None 表示拦截（阻止后续处理与主流程）。
        单个处理器异常：记录日志并跳过（DEVELOP.md 4.2: 不影响主流程）。
        """
        handlers = sorted(self._intercept.get(event, []), key=lambda t: -t[0])
        for _, handler in handlers:
            try:
                result = await handler(payload)
            except Exception as exc:
                logger.error("Intercept 处理器异常，已跳过", event_type=event.value, error=str(exc), exc_info=True)
                continue
            if result is None:
                logger.debug("事件被拦截", event_type=event.value)
                return None
            payload = result
        return payload

    async def fire_async(self, event: EventType, payload: Any) -> None:
        """并发执行 Async 处理器，异常隔离。"""
        # R10: 快照 handler 列表, 防止 handler 执行中注册同事件 handler 触发
        # "RuntimeError: list changed size during iteration" (asyncio.gather
        # 内部生成器会迭代源列表)。
        handlers = list(self._async.get(event, ()))
        if not handlers:
            return
        results = await asyncio.gather(*(h(payload) for h in handlers), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("Async 处理器异常", event_type=event.value, error=str(result), exc_info=result)


def _filter_by_source(
    items_map: dict[EventType, list[Any]],
    sources_map: dict[EventType, list[str]],
    event: EventType,
    source: str,
) -> int:
    """就地过滤掉指定来源的处理器, 返回被移除数量 (C2: EventBus.deregister_by_source 用)。"""
    items = items_map.get(event)
    if items is None:
        return 0
    srcs = sources_map.get(event, [])
    keep = [(it, s) for it, s in zip(items, srcs) if s != source]
    removed = len(items) - len(keep)
    items_map[event] = [it for it, _ in keep]
    sources_map[event] = [s for _, s in keep]
    return removed
