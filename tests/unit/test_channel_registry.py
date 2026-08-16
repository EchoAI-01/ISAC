"""N5b 批次G: ChannelRegistry.start_all/stop_all 错误隔离测试。

此前 start_all/stop_all 裸 for + await, 单个适配器 start()/stop() 抛异常会中断
循环, 后续平台不再启动/停止。修复后单平台失败仅告警, 其余继续。
"""

from __future__ import annotations

import pytest

from isac.channel.base import PlatformAdapter
from isac.channel.model import ISACMessage
from isac.channel.registry import ChannelRegistry


class _FakeAdapter(PlatformAdapter):
    """可控平台适配器: start/stop 可注入异常或记录调用。"""

    def __init__(
        self,
        name: str,
        *,
        start_raises: Exception | None = None,
        stop_raises: Exception | None = None,
    ) -> None:
        self._name = name
        self._start_raises = start_raises
        self._stop_raises = stop_raises
        self.started = False
        self.stopped = False

    @property
    def platform_name(self) -> str:
        return self._name

    async def start(self) -> None:
        self.started = True
        if self._start_raises is not None:
            raise self._start_raises

    async def stop(self) -> None:
        self.stopped = True
        if self._stop_raises is not None:
            raise self._stop_raises

    async def send(self, message: ISACMessage) -> bool:
        return True


@pytest.mark.asyncio
async def test_start_all_continues_after_one_adapter_raises() -> None:
    """第一个适配器 start 抛异常, 后续适配器仍应启动。"""
    registry = ChannelRegistry()
    bad = _FakeAdapter("bad_platform", start_raises=RuntimeError("boom"))
    good = _FakeAdapter("good_platform")
    registry.register(bad)
    registry.register(good)

    await registry.start_all()  # 不应抛异常

    assert bad.started is True  # start 被调用 (异常在标记后抛)
    assert good.started is True  # 后续适配器未被中断


@pytest.mark.asyncio
async def test_start_all_all_adapters_started_when_no_error() -> None:
    registry = ChannelRegistry()
    a = _FakeAdapter("p1")
    b = _FakeAdapter("p2")
    c = _FakeAdapter("p3")
    for adp in (a, b, c):
        registry.register(adp)

    await registry.start_all()

    assert a.started and b.started and c.started


@pytest.mark.asyncio
async def test_stop_all_continues_after_one_adapter_raises() -> None:
    """关闭时一个适配器 stop 抛异常, 其余仍应被停止 (避免连接/子进程泄漏残留)。"""
    registry = ChannelRegistry()
    bad = _FakeAdapter("bad_platform", stop_raises=RuntimeError("boom"))
    good = _FakeAdapter("good_platform")
    registry.register(bad)
    registry.register(good)

    await registry.stop_all()  # 不应抛异常

    assert bad.stopped is True
    assert good.stopped is True


@pytest.mark.asyncio
async def test_stop_all_with_error_in_middle_does_not_skip_rest() -> None:
    """中间适配器失败, 其后的适配器仍被停止。"""
    registry = ChannelRegistry()
    a = _FakeAdapter("p1")
    mid = _FakeAdapter("p2", stop_raises=ValueError("mid fail"))
    c = _FakeAdapter("p3")
    for adp in (a, mid, c):
        registry.register(adp)

    await registry.stop_all()

    assert a.stopped and mid.stopped and c.stopped
