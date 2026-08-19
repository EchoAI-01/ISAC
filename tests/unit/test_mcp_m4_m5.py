"""#27 (tools M4+M5): MCP Channel 门控接线 + 崩溃感知重连。

M4: EnableMatrix.is_mcp_enabled 此前零生产调用 (死代码); 现接线层
(_wire_mcp_clients) 与调用层 (registry.effective_policy 对 mcp:* 按 platform) 双接线。
M5: MCP stdio server 崩溃此前无感知无重连; 现 is_alive 检测 + ensure_connected
自动重连一次。
"""

from __future__ import annotations

import pytest

from isac.agent.tools.base import ToolPermission
from isac.agent.tools.mcp.client import MCPClient
from isac.agent.tools.registry import ToolRegistry
from isac.core.policy import EnableMatrix

# ── M4: EnableMatrix MCP 门控 ──────────────────────────────────


def test_mcp_channel_enabled_default_allow() -> None:
    matrix = EnableMatrix()
    assert matrix.mcp_channel_enabled("srv", "qq") is True
    assert matrix.mcp_channel_enabled("srv", "") is True


def test_mcp_channel_disabled_for_platform() -> None:
    matrix = EnableMatrix(channel_overrides={"qq": {"mcp": {"srv": False}}})
    assert matrix.mcp_channel_enabled("srv", "qq") is False
    # 其他平台不受影响
    assert matrix.mcp_channel_enabled("srv", "telegram") is True


def test_is_mcp_enabled_whitelist_and_channel() -> None:
    matrix = EnableMatrix(channel_overrides={"qq": {"mcp": {"srv": False}}})
    # 不在 Agent 白名单 → False
    assert matrix.is_mcp_enabled("srv", [], agent_id="a") is False
    # 在白名单但 Channel 禁用 → False
    assert matrix.is_mcp_enabled("srv", ["srv"], agent_id="a", platform="qq") is False
    # 白名单 + 其他平台 → True
    assert matrix.is_mcp_enabled("srv", ["srv"], agent_id="a", platform="telegram") is True


# ── M4: 调用层 effective_policy 对 mcp:* 按平台门控 ────────────


def test_effective_policy_denies_mcp_tool_when_channel_disabled() -> None:
    matrix = EnableMatrix(channel_overrides={"qq": {"mcp": {"srv1": False}}})
    registry = ToolRegistry(
        ToolPermission({"mcp:srv1:search": "restricted"}), enable_matrix=matrix
    )
    # qq 平台禁用 srv1 → mcp:srv1:search 被拒
    assert registry.effective_policy("mcp:srv1:search", platform="qq") == "deny"
    # 其他平台不受影响
    assert registry.effective_policy("mcp:srv1:search", platform="telegram") == "restricted"


def test_effective_policy_non_mcp_tool_unaffected_by_mcp_gate() -> None:
    matrix = EnableMatrix(channel_overrides={"qq": {"mcp": {"srv1": False}}})
    registry = ToolRegistry(ToolPermission({"bash": "allow"}), enable_matrix=matrix)
    assert registry.effective_policy("bash", platform="qq") == "allow"


# ── M5: 存活检测 + 崩溃重连 ────────────────────────────────────


class _FakeProcess:
    def __init__(self, alive: bool = True) -> None:
        self.returncode = None if alive else 0
        self.stdin = None
        self.stdout = None
        self.stderr = None


def test_is_alive_stdio_dead_process() -> None:
    client = MCPClient("srv", {"transport": "stdio", "command": "x"})
    client._connected = True
    client._process = _FakeProcess(alive=False)
    assert client.is_alive() is False


def test_is_alive_stdio_live_process() -> None:
    client = MCPClient("srv", {"transport": "stdio", "command": "x"})
    client._connected = True
    client._process = _FakeProcess(alive=True)
    assert client.is_alive() is True


def test_is_alive_not_connected() -> None:
    client = MCPClient("srv", {"transport": "stdio", "command": "x"})
    assert client.is_alive() is False


@pytest.mark.asyncio
async def test_ensure_connected_no_reconnect_when_never_connected() -> None:
    """从未连接/已主动断开 → 不自动重连 (无人期望它活着)。"""
    client = MCPClient("srv", {"transport": "stdio", "command": "x"})
    assert await client.ensure_connected() is False


@pytest.mark.asyncio
async def test_ensure_connected_reconnects_after_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """崩溃 (曾连接但进程死亡) → 自动重连一次。"""
    client = MCPClient("srv", {"transport": "stdio", "command": "x"})
    client._connected = True
    client._process = _FakeProcess(alive=False)

    disconnected: list[bool] = []
    connected: list[bool] = []

    async def _fake_disconnect() -> None:
        disconnected.append(True)
        client._connected = False

    async def _fake_connect() -> None:
        connected.append(True)
        client._connected = True
        client._process = _FakeProcess(alive=True)

    monkeypatch.setattr(client, "disconnect", _fake_disconnect)
    monkeypatch.setattr(client, "connect", _fake_connect)
    assert await client.ensure_connected() is True
    assert disconnected == [True] and connected == [True]
    assert client.is_alive() is True


@pytest.mark.asyncio
async def test_call_tool_unrecoverable_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """重连失败 → call_tool 返回明确错误 (不抛异常)。"""
    client = MCPClient("srv", {"transport": "stdio", "command": "x"})

    async def _fail_ensure() -> bool:
        return False

    monkeypatch.setattr(client, "ensure_connected", _fail_ensure)
    result = await client.call_tool("some_tool", {})
    assert result.is_error is True
    assert "不可用" in result.content


# ── M4: 接线层 _wire_mcp_clients 门控 ──────────────────────────


@pytest.mark.asyncio
async def test_wire_mcp_clients_calls_enable_matrix_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """接线层经 is_mcp_enabled 门控 (M4: 此前零生产调用); 禁用的 server 跳过接线。"""
    from isac.runtime.assembly import _wire_mcp_clients
    from isac.runtime.config import AgentConfig
    from isac.runtime.services import ServiceContainer

    connected: list[str] = []

    class _FakeClient:
        def __init__(self, name: str, cfg: dict) -> None:
            self.name = name

        async def connect(self) -> None:
            connected.append(self.name)

        async def list_tools(self) -> list:
            return []

        async def disconnect(self) -> None:
            pass

    monkeypatch.setattr("isac.agent.tools.mcp.client.MCPClient", _FakeClient)

    class _SpyMatrix(EnableMatrix):
        def __init__(self, denied: set) -> None:
            super().__init__()
            self._denied = denied
            self.checked: list[str] = []

        def is_mcp_enabled(self, server_name, agent_mcp_servers, agent_id="", platform="") -> bool:
            self.checked.append(server_name)
            return server_name not in self._denied

    services = ServiceContainer({
        "mcp_servers": {"srv1": {"transport": "stdio", "command": "x"},
                        "srv2": {"transport": "stdio", "command": "y"}},
    })
    config = AgentConfig(agent_id="a", display_name="A", mcp_servers=["srv1", "srv2"])
    tools = ToolRegistry(ToolPermission())
    matrix = _SpyMatrix(denied={"srv2"})

    clients = await _wire_mcp_clients(config, services, tools, matrix)
    # 两个 server 都过了门控检查; srv2 被禁 → 只接了 srv1
    assert matrix.checked == ["srv1", "srv2"]
    assert connected == ["srv1"]
    assert len(clients) == 1


@pytest.mark.asyncio
async def test_wire_mcp_clients_no_matrix_backward_compat(monkeypatch: pytest.MonkeyPatch) -> None:
    """enable_matrix=None 时回退直连 (向后兼容)。"""
    from isac.runtime.assembly import _wire_mcp_clients
    from isac.runtime.config import AgentConfig
    from isac.runtime.services import ServiceContainer

    class _FakeClient:
        def __init__(self, name: str, cfg: dict) -> None:
            self.name = name

        async def connect(self) -> None:
            pass

        async def list_tools(self) -> list:
            return []

        async def disconnect(self) -> None:
            pass

    monkeypatch.setattr("isac.agent.tools.mcp.client.MCPClient", _FakeClient)
    services = ServiceContainer({"mcp_servers": {"srv1": {"transport": "stdio", "command": "x"}}})
    config = AgentConfig(agent_id="a", display_name="A", mcp_servers=["srv1"])
    tools = ToolRegistry(ToolPermission())
    clients = await _wire_mcp_clients(config, services, tools)  # 无矩阵
    assert len(clients) == 1
