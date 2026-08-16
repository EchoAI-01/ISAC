"""N5b 批次C C3+C4: 隔离 host 崩溃重载 + correlation_id 校验测试。

C3: load_plugin 缓存 plugin_path; _on_crash respawn 后标记 _needs_reload 让下次
call 重载 (此前 respawn 空 worker 不 reload → 后续 call 报"插件尚未加载")。
C3-2: _apply_rlimits 接 rlimits 参数 (此前 RLIMIT_CPU (1,1) 硬编码)。
C4: _ipc_roundtrip 校验响应 correlation_id 匹配 (此前 FIFO recv, 错配响应拿到别人结果)。
"""

from __future__ import annotations

import pytest

from isac.plugin.isolation.host import PluginIsolationHost, _apply_rlimits
from isac.plugin.isolation.protocol import IPCEnvelope


def test_apply_rlimits_accepts_custom_config_without_raising() -> None:
    """C3-2: rlimits 可配, 默认 None 用内置默认; 权限不足时静默跳过 (不抛)。"""
    _apply_rlimits({"cpu": (2, 2), "nofile": (128, 128)})
    _apply_rlimits(None)  # 默认
    _apply_rlimits({})  # 空 dict → 用默认


def test_host_init_accepts_rlimits_param() -> None:
    """C3-2: PluginIsolationHost(rlimits=...) 缓存配置供 spawn 透传。"""
    cfg = {"cpu": (5, 5)}
    host = PluginIsolationHost("p1", rlimits=cfg)
    assert host._rlimits is cfg  # noqa: SLF001
    # 默认 None
    assert PluginIsolationHost("p2")._rlimits is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_load_plugin_caches_plugin_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """C3: load_plugin 缓存 plugin_path, 供 _on_crash respawn 后重载。"""
    host = PluginIsolationHost("p1")

    async def _fake_call(envelope: IPCEnvelope) -> IPCEnvelope:
        return IPCEnvelope(kind="result", plugin_id="p1", payload={})

    monkeypatch.setattr(host, "call", _fake_call)
    await host.load_plugin("/some/plugin/path")
    assert host._plugin_path == "/some/plugin/path"  # noqa: SLF001


@pytest.mark.asyncio
async def test_ipc_roundtrip_rejects_mismatched_correlation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """C4: 响应 correlation_id 不匹配 (管道残留/并发错配) → 视为崩溃重置, 不返回错配结果。"""
    host = PluginIsolationHost("p1")
    host._alive = True  # noqa: SLF001

    class _Conn:
        sent: list[str] = []

        def send(self, data: str) -> None:
            _Conn.sent.append(data)

        def recv(self) -> str:
            # 返回一个 correlation_id 不匹配的响应
            return '{"correlation_id": "corr-wrong", "kind": "result", "plugin_id": "p1", "payload": {}}'

    host._parent_conn = _Conn()  # noqa: SLF001
    crashed: list[bool] = []

    async def _noop_crash() -> None:
        crashed.append(True)
        host._alive = False  # noqa: SLF001

    monkeypatch.setattr(host, "_on_crash", _noop_crash)
    env = IPCEnvelope(kind="call", plugin_id="p1", payload={})
    env.correlation_id = "corr-1"
    with pytest.raises(RuntimeError, match="错配"):
        await host._ipc_roundtrip(env)
    assert crashed == [True]  # 触发了崩溃重置


@pytest.mark.asyncio
async def test_ipc_roundtrip_accepts_matching_correlation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """C4 回归: correlation_id 匹配时正常返回 (不误触发崩溃)。"""
    host = PluginIsolationHost("p1")
    host._alive = True  # noqa: SLF001

    class _Conn:
        def send(self, data: str) -> None:
            pass

        def recv(self) -> str:
            return '{"correlation_id": "corr-1", "kind": "result", "plugin_id": "p1", "payload": {"echo": "ok"}}'

    host._parent_conn = _Conn()  # noqa: SLF001
    monkeypatch.setattr(host, "_on_crash", _noop_async)  # 不应被调
    env = IPCEnvelope(kind="call", plugin_id="p1", payload={})
    env.correlation_id = "corr-1"
    data = await host._ipc_roundtrip(env)  # noqa: SLF001
    assert data["payload"]["echo"] == "ok"


async def _noop_async() -> None:
    pass
