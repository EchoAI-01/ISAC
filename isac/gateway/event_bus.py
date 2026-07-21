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

    def on_intercept(self, event: EventType, handler: InterceptHandler, priority: int = 0) -> None:
        """注册 Intercept 处理器。priority 越大越先执行。"""
        self._intercept.setdefault(event, []).append((priority, handler))

    def on_async(self, event: EventType, handler: AsyncHandler) -> None:
        """注册 Async 处理器（并发执行）。"""
        self._async.setdefault(event, []).append(handler)

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
        handlers = self._async.get(event, [])
        if not handlers:
            return
        results = await asyncio.gather(*(h(payload) for h in handlers), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("Async 处理器异常", event_type=event.value, error=str(result), exc_info=result)
