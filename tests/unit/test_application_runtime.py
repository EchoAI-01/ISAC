"""ApplicationRuntime 生命周期 smoke test (K1, DEVELOPMENT_PLAN.md)。

覆盖:
- register_lifecycle 启动按顺序、关闭按 LIFO
- spawn 挂到 TaskGroup, 持有强引用不被 GC
- request_stop 触发 serve_forever 退出
- 启动失败时已启动资源按 LIFO 回滚
- 三种驻留模式: 无 Channel / 仅 Control / 启用 Channel
"""

from __future__ import annotations

import asyncio

import pytest

from isac.runtime.application import ApplicationRuntime


class _FakeResource:
    """记录启动/停止顺序的可观察资源。"""

    def __init__(self, name: str, events: list[str], *, fail_start: bool = False) -> None:
        self.name = name
        self._events = events
        self._fail_start = fail_start
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        if self._fail_start:
            raise RuntimeError(f"{self.name} start failed")
        self.started = True
        self._events.append(f"start:{self.name}")

    async def stop(self) -> None:
        self.stopped = True
        self._events.append(f"stop:{self.name}")


@pytest.mark.asyncio
async def test_lifecycle_starts_in_registration_order() -> None:
    """启动按 register_lifecycle 顺序, 关闭按 LIFO 倒序 (K1)。"""
    events: list[str] = []
    r1 = _FakeResource("r1", events)
    r2 = _FakeResource("r2", events)
    r3 = _FakeResource("r3", events)

    runtime = ApplicationRuntime()
    runtime.register_lifecycle("r1", r1.start, r1.stop)
    runtime.register_lifecycle("r2", r2.start, r2.stop)
    runtime.register_lifecycle("r3", r3.start, r3.stop)

    await runtime.start()
    assert r1.started and r2.started and r3.started
    assert events == ["start:r1", "start:r2", "start:r3"]

    runtime.request_stop()
    await runtime.serve_forever()
    await runtime.shutdown()

    assert r1.stopped and r2.stopped and r3.stopped
    # 关闭 LIFO 倒序
    assert events == ["start:r1", "start:r2", "start:r3", "stop:r3", "stop:r2", "stop:r1"]


@pytest.mark.asyncio
async def test_start_failure_rolls_back_already_started_resources() -> None:
    """启动失败时, 已启动的资源按 LIFO 倒序 stop (K1)。"""
    events: list[str] = []
    r1 = _FakeResource("r1", events)
    r2 = _FakeResource("r2", events, fail_start=True)

    runtime = ApplicationRuntime()
    runtime.register_lifecycle("r1", r1.start, r1.stop)
    runtime.register_lifecycle("r2", r2.start, r2.stop)

    with pytest.raises(RuntimeError, match="r2 start failed"):
        await runtime.start()

    assert r1.started and r1.stopped  # 已启动, 被回滚停止
    assert not r2.started
    assert events == ["start:r1", "stop:r1"]
    # runtime 处于未启动状态, 可再次 start
    assert not runtime.started


@pytest.mark.asyncio
async def test_spawn_holds_strong_reference_until_shutdown() -> None:
    """spawn 的 task 被持有强引用, 不被 GC, 关闭时统一 cancel+await (K1)。"""
    runtime = ApplicationRuntime()
    await runtime.start()

    completed = asyncio.Event()

    async def _long_running() -> None:
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            completed.set()
            raise

    task = runtime.spawn(_long_running(), name="test-task")
    # 让 task 真正开始执行, 进入 sleep 后再触发 cancel
    await asyncio.sleep(0)
    assert not task.done()

    runtime.request_stop()
    await runtime.serve_forever()
    await runtime.shutdown()

    # shutdown 触发显式 cancel + TaskGroup __aexit__ 等待
    assert completed.is_set()
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_request_stop_unblocks_serve_forever() -> None:
    """request_stop 触发 _stop_event, serve_forever 退出 (K1)。"""
    runtime = ApplicationRuntime()
    await runtime.start()

    async def _stopper() -> None:
        await asyncio.sleep(0.05)
        runtime.request_stop()

    asyncio.create_task(_stopper())
    await runtime.serve_forever()
    await runtime.shutdown()
    assert not runtime.started


@pytest.mark.asyncio
async def test_signal_handlers_installed_without_error() -> None:
    """install_signal_handlers 不抛异常 (主线程环境, K1)。"""
    runtime = ApplicationRuntime()
    runtime.install_signal_handlers()
    # 不抛异常即可; 清理 handler
    runtime.remove_signal_handlers()


@pytest.mark.asyncio
async def test_mode_no_channel_only_resident() -> None:
    """无 Channel 模式: runtime 仍持续驻留直到 request_stop (K1 验收三种模式之一)。"""
    runtime = ApplicationRuntime()
    # 不注册任何 channel, 仅注册一个 noop 资源
    noop = _FakeResource("noop", [])
    runtime.register_lifecycle("noop", noop.start, noop.stop)

    await runtime.start()
    assert noop.started

    asyncio.get_running_loop().call_later(0.05, runtime.request_stop)
    await runtime.serve_forever()
    await runtime.shutdown()

    assert noop.stopped


@pytest.mark.asyncio
async def test_mode_control_plane_only_resident() -> None:
    """仅 Control 模式: 注册 control_plane 生命周期 + alert, request_stop 后优雅退出 (K1)。"""
    events: list[str] = []
    control = _FakeResource("control", events)
    alert = _FakeResource("alert", events)

    runtime = ApplicationRuntime()
    runtime.register_lifecycle("control", control.start, control.stop)
    runtime.register_lifecycle("alert", alert.start, alert.stop)

    await runtime.start()

    asyncio.get_running_loop().call_later(0.05, runtime.request_stop)
    await runtime.serve_forever()
    await runtime.shutdown()

    # 启动顺序 control→alert, 关闭 LIFO alert→control
    assert events == ["start:control", "start:alert", "stop:alert", "stop:control"]


@pytest.mark.asyncio
async def test_mode_with_channel_resident() -> None:
    """启用 Channel 模式: channel + control + alert 三层驻留 + LIFO 关闭 (K1)。"""
    events: list[str] = []
    channel = _FakeResource("channel", events)
    control = _FakeResource("control", events)
    alert = _FakeResource("alert", events)

    runtime = ApplicationRuntime()
    runtime.register_lifecycle("channel", channel.start, channel.stop)
    runtime.register_lifecycle("control", control.start, control.stop)
    runtime.register_lifecycle("alert", alert.start, alert.stop)

    await runtime.start()

    asyncio.get_running_loop().call_later(0.05, runtime.request_stop)
    await runtime.serve_forever()
    await runtime.shutdown()

    # 启动 channel→control→alert, 关闭 alert→control→channel
    assert events == [
        "start:channel", "start:control", "start:alert",
        "stop:alert", "stop:control", "stop:channel",
    ]


@pytest.mark.asyncio
async def test_shutdown_idempotent() -> None:
    """多次 shutdown 不会重复 stop 资源 (K1)。"""
    events: list[str] = []
    r1 = _FakeResource("r1", events)
    runtime = ApplicationRuntime()
    runtime.register_lifecycle("r1", r1.start, r1.stop)

    await runtime.start()
    runtime.request_stop()
    await runtime.serve_forever()
    await runtime.shutdown()
    assert events == ["start:r1", "stop:r1"]

    # 二次 shutdown 不重复 stop
    await runtime.shutdown()
    assert events == ["start:r1", "stop:r1"]
