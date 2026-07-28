"""EventBus 双层事件单元测试。"""

from __future__ import annotations

import asyncio

from isac.core.events import EventType
from isac.gateway.event_bus import EventBus


def run(coro):
    return asyncio.run(coro)


class TestInterceptChain:
    def test_priority_order_and_modify(self):
        bus = EventBus()
        calls = []

        async def high(payload):
            calls.append("high")
            return payload + 1

        async def low(payload):
            calls.append("low")
            return payload * 2

        bus.on_intercept(EventType.ON_MESSAGE, low, priority=0)
        bus.on_intercept(EventType.ON_MESSAGE, high, priority=10)

        result = run(bus.fire_intercept(EventType.ON_MESSAGE, 1))
        assert calls == ["high", "low"]  # 高优先级先执行
        assert result == 4  # (1+1)*2

    def test_block_on_none(self):
        bus = EventBus()

        async def blocker(payload):
            return None

        async def after(payload):
            raise AssertionError("不应执行到")

        bus.on_intercept(EventType.ON_MESSAGE, blocker, priority=10)
        bus.on_intercept(EventType.ON_MESSAGE, after, priority=0)

        assert run(bus.fire_intercept(EventType.ON_MESSAGE, "x")) is None

    def test_handler_exception_isolated(self):
        bus = EventBus()

        async def bad(payload):
            raise RuntimeError("boom")

        async def good(payload):
            return "ok"

        bus.on_intercept(EventType.ON_MESSAGE, bad, priority=10)
        bus.on_intercept(EventType.ON_MESSAGE, good, priority=0)

        assert run(bus.fire_intercept(EventType.ON_MESSAGE, "x")) == "ok"


class TestAsyncHandlers:
    def test_async_concurrent_and_isolated(self):
        bus = EventBus()
        seen = []

        async def bad(payload):
            raise RuntimeError("boom")

        async def good(payload):
            seen.append(payload)

        bus.on_async(EventType.POST_MESSAGE, bad)
        bus.on_async(EventType.POST_MESSAGE, good)

        run(bus.fire_async(EventType.POST_MESSAGE, "done"))
        assert seen == ["done"]

    def test_async_handler_registering_same_event_during_fire(self):
        """R10: handler 执行中注册同事件 handler 不触发
        "RuntimeError: list changed size during iteration"。

        asyncio.gather 内部用源列表迭代, 若 fire_async 直接持有内部列表
        引用, 注册新 handler 会让 gather 抛 RuntimeError。快照副本后隔离。
        """
        bus = EventBus()
        seen: list[str] = []

        async def first(payload):
            seen.append("first")
            # 执行中注册同事件 handler, 触发源列表修改
            bus.on_async(EventType.POST_MESSAGE, second)

        async def second(payload):
            seen.append("second")

        bus.on_async(EventType.POST_MESSAGE, first)

        # 不应抛 RuntimeError, first 正常执行, second 不被本轮 gather 覆盖
        run(bus.fire_async(EventType.POST_MESSAGE, "x"))
        assert seen == ["first"]

        # 第二次 fire 时 first 与 second 都在快照里, 都会被执行
        run(bus.fire_async(EventType.POST_MESSAGE, "y"))
        assert seen == ["first", "first", "second"]
