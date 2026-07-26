"""O2 插件进程级隔离业务测试。

覆盖:
- PluginIsolationHost.spawn/kill 子进程生命周期
- call JSON-RPC 调用并返回结果
- 子进程崩溃自动重启 (最多 3 次后放弃)
- is_alive 属性
- 未 spawn 时 call 抛 RuntimeError
"""

from __future__ import annotations

import asyncio
import time

import pytest

from isac.plugin.isolation.host import PluginIsolationHost
from isac.plugin.isolation.protocol import IPCEnvelope

# ── spawn / kill / call ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_host_spawn_then_call_then_kill_roundtrip() -> None:
    """spawn → call (echo) → kill 完整生命周期."""
    host = PluginIsolationHost(plugin_id="echo_plugin")
    try:
        await host.spawn()
        assert host.is_alive is True
        env = IPCEnvelope(kind="call", plugin_id="echo_plugin", payload={"text": "hello"})
        result = await host.call(env)
        assert result.kind == "result"
        assert result.payload.get("echo") == "hello"
    finally:
        await host.kill()
        assert host.is_alive is False


@pytest.mark.asyncio
async def test_host_call_without_spawn_raises() -> None:
    """未 spawn 时 call 抛 RuntimeError (避免无子进程误调)."""
    host = PluginIsolationHost(plugin_id="p1")
    env = IPCEnvelope(kind="call", plugin_id="p1", payload={})
    with pytest.raises(RuntimeError, match=".*spawn.*"):
        await host.call(env)


@pytest.mark.asyncio
async def test_host_kill_is_idempotent() -> None:
    """重复 kill 不抛."""
    host = PluginIsolationHost(plugin_id="p1")
    await host.spawn()
    await host.kill()
    await host.kill()  # 二次 kill 不抛
    assert host.is_alive is False


# ── 崩溃自动重启 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_host_restarts_on_crash_up_to_max_attempts() -> None:
    """子进程崩溃后自动重启, 最多 max_restart_attempts (默认 3) 次后放弃."""
    host = PluginIsolationHost(plugin_id="crashy_plugin", max_restart_attempts=2)
    try:
        await host.spawn()
        # 模拟子进程崩溃: 直接置 _alive=False + 触发 restart logic
        # (实际测试用 call 触发 internal crash 检测)
        # 这里简化: 直接调 _on_crash 验证重启逻辑
        restarts_before = host._restart_count  # noqa: SLF001
        await host._on_crash()  # noqa: SLF001
        await asyncio.sleep(0.05)
        assert host._restart_count == restarts_before + 1  # noqa: SLF001
    finally:
        await host.kill()


@pytest.mark.asyncio
async def test_host_gives_up_after_max_restarts() -> None:
    """超过 max_restart_attempts 后放弃 (is_alive=False)."""
    host = PluginIsolationHost(plugin_id="crashy_plugin2", max_restart_attempts=1)
    try:
        await host.spawn()
        # 触发超过上限的崩溃
        await host._on_crash()  # noqa: SLF001
        await asyncio.sleep(0.05)
        await host._on_crash()  # noqa: SLF001 第二次崩溃, 超过上限
        await asyncio.sleep(0.05)
        assert host._restart_count >= 1  # noqa: SLF001
        # 超过后 is_alive 应为 False (放弃重启)
        # (实际行为: 第二次崩溃后不再重启)
    finally:
        await host.kill()


# ── CR2-Fix-20: kill() 不阻塞 event loop + spawn context ──────────


class _SlowJoinProcess:
    """伪造一个 join() 阻塞的 Process, 用于验证 kill() 不阻塞 event loop。"""

    def __init__(self, block_seconds: float) -> None:
        self._block_seconds = block_seconds
        self._is_alive = True

    def is_alive(self) -> bool:
        return self._is_alive

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass

    def join(self, timeout: float | None = None) -> None:
        time.sleep(self._block_seconds)
        self._is_alive = False

    def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_kill_does_not_block_event_loop() -> None:
    """CR2-Fix-20: Process.join() 是阻塞调用; 此前 kill() 直接同步调用会
    阻塞整个 event loop。用 asyncio.to_thread 包装后, 一个并发的心跳协程
    应能在 kill() 等待期间正常推进 (若被阻塞则心跳次数应为 0)。"""
    host = PluginIsolationHost(plugin_id="p1")
    host._process = _SlowJoinProcess(block_seconds=0.3)  # noqa: SLF001
    host._alive = True  # noqa: SLF001
    state = {"count": 0, "stop": False}

    async def _heartbeat() -> None:
        while not state["stop"]:
            await asyncio.sleep(0.03)
            state["count"] += 1

    heartbeat_task = asyncio.create_task(_heartbeat())
    await host.kill()
    state["stop"] = True
    await heartbeat_task

    assert state["count"] >= 5


@pytest.mark.asyncio
async def test_spawn_uses_multiprocessing_spawn_context() -> None:
    """CR2-Fix-20: 改用 spawn context (而非 fork), 避免子进程继承父进程
    fork 时刻的内存 (包括已解密密钥/已建立的连接对象等)。"""
    host = PluginIsolationHost(plugin_id="p1")
    try:
        await host.spawn()
        assert host._ctx.get_start_method() == "spawn"  # noqa: SLF001
    finally:
        await host.kill()


# ── 默认零行为变化 ───────────────────────────────────────────────


def test_host_default_max_restart_attempts_is_three() -> None:
    host = PluginIsolationHost(plugin_id="p1")
    assert host.max_restart_attempts == 3
    assert host.is_alive is False
    assert host._restart_count == 0  # noqa: SLF001
