"""U6 插件隔离默认化专项测试 (信任分级倒转)。

验收覆盖 (DEVELOPMENT_PLAN §四 U6):
- 市场/git/url/upload 安装的插件默认隔离 host 运行 (未声明 trust=hosted 即进沙箱);
- hosted 信任需 manifest 声明 + 部署方 trust_hosted 显式确认;
- rlimits/ipc_timeout/max_restart_attempts 从部署配置接线;
- 运行中 Agent 的插件 hooks 卸载后同步清除 (零残留);
- 兼容层插件无 manifest 不可隔离 → 宿主进程内加载 (降级承诺, 文档化)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from isac.plugin.runtime.manager import PluginManager


def _make_native(root: Path, name: str, *, trust: str | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True)
    manifest: dict[str, Any] = {"name": name, "entry": "plugin.py"}
    if trust is not None:
        manifest["trust"] = trust
    (d / "manifest.jsonc").write_text(json.dumps(manifest), encoding="utf-8")
    (d / "plugin.py").write_text(
        "from isac.plugin.native.plugin import ISACPlugin\n"
        "class P(ISACPlugin):\n"
        "    def ping(self):\n"
        "        return 'pong'\n",
        encoding="utf-8",
    )
    return d


def _make_compat(root: Path, name: str) -> Path:
    """AstrBot 兼容层插件 (metadata.yaml, 无 manifest.jsonc)。"""
    d = root / name
    d.mkdir(parents=True)
    (d / "metadata.yaml").write_text(f"name: {name}\n", encoding="utf-8")
    (d / "plugin.py").write_text(
        "from isac.plugin.compatibility.astrbot.star import Star\n"
        "class CompatStar(Star):\n"
        "    pass\n",
        encoding="utf-8",
    )
    return d


# ── 默认隔离 (市场安装场景) ──────────────────────────────────


@pytest.mark.asyncio
async def test_installed_plugin_defaults_to_isolated(tmp_path: Path) -> None:
    """市场安装场景: install → 未声明 trust=hosted 的插件默认隔离加载。"""
    plugins_dir = tmp_path / "plugins"

    class _FakeInstaller:
        async def install(self, source: dict) -> Path:
            return _make_native(plugins_dir, source["name"])

    pm = PluginManager({})
    pm._plugins_dir = plugins_dir
    try:
        status = await pm.install({"type": "market", "name": "market_plug"}, _FakeInstaller())
        assert status == "loaded (isolated)"
        assert pm.is_isolated("market_plug") is True
        assert pm.get("market_plug") is None  # 不在宿主进程 _loaded
        # 子进程真实加载, IPC 可调
        assert await pm.call_isolated("market_plug", "ping") == "pong"
    finally:
        await pm.shutdown()


@pytest.mark.asyncio
async def test_hosted_trust_without_confirmation_still_isolated(tmp_path: Path) -> None:
    """声明 trust=hosted 但部署方未在 trust_hosted 确认 → 仍隔离 (不轻信 manifest)。"""
    plugins_dir = tmp_path / "plugins"

    class _FakeInstaller:
        async def install(self, source: dict) -> Path:
            return _make_native(plugins_dir, source["name"], trust="hosted")

    pm = PluginManager({})
    pm._plugins_dir = plugins_dir
    try:
        status = await pm.install({"type": "market", "name": "sneaky"}, _FakeInstaller())
        assert status == "loaded (isolated)"
        assert pm.is_isolated("sneaky") is True
    finally:
        await pm.shutdown()


@pytest.mark.asyncio
async def test_compat_plugin_degrades_to_host_with_warning_path(tmp_path: Path) -> None:
    """兼容层降级承诺: 无 manifest 的 AstrBot 插件不可隔离, 宿主进程内加载。"""
    root = tmp_path / "plugins"
    root.mkdir()
    _make_compat(root, "astrbot_plug")
    pm = PluginManager({})
    report = await pm.load_all(root)
    assert "loaded" in report["astrbot_plug"]
    assert pm.is_isolated("astrbot_plug") is False
    # 兼容层 LoadedPlugin.name 为 Star 类名 (非目录名), 在宿主进程 _loaded 内
    assert "CompatStar" in pm.list_loaded()
    assert pm.get("CompatStar") is not None


# ── rlimits / ipc_timeout 配置接线 ───────────────────────────


def test_isolation_host_kwargs_from_config() -> None:
    """plugins.isolation 配置解析为 PluginIsolationHost 构造参数。"""
    pm = PluginManager(
        {
            "isolation": {
                "rlimits": {"cpu": [30, 30], "nofile": [32, 32], "as": [1024, 1024]},
                "ipc_timeout_seconds": 12.5,
                "max_restart_attempts": 5,
            }
        }
    )
    kwargs = pm._isolation_host_kwargs()
    assert kwargs["rlimits"] == {"cpu": (30, 30), "nofile": (32, 32), "as": (1024, 1024)}
    assert kwargs["ipc_timeout"] == 12.5
    assert kwargs["max_restart_attempts"] == 5


def test_isolation_host_kwargs_absent_defaults_empty() -> None:
    """未配置 isolation 节 → 空 kwargs (PluginIsolationHost 用内置默认)。"""
    assert PluginManager({})._isolation_host_kwargs() == {}
    # 非法值安全忽略
    bad_cfg = {"isolation": {"ipc_timeout_seconds": "abc", "rlimits": {"cpu": [1]}}}
    assert PluginManager(bad_cfg)._isolation_host_kwargs() == {}


@pytest.mark.asyncio
async def test_rlimits_wired_into_isolation_host(tmp_path: Path) -> None:
    """rlimits/ipc_timeout 真实传给隔离宿主 (生效验证)。"""
    root = tmp_path / "plugins"
    root.mkdir()
    _make_native(root, "limited")
    pm = PluginManager(
        {
            "isolation": {
                "rlimits": {"cpu": [45, 45]},
                "ipc_timeout_seconds": 9.0,
                "max_restart_attempts": 2,
            }
        }
    )
    try:
        await pm.load_all(root)
        host = pm._iso_hosts["limited"]
        assert host._rlimits == {"cpu": (45, 45)}
        assert host._ipc_timeout == 9.0
        assert host.max_restart_attempts == 2
    finally:
        await pm.shutdown()


# ── 卸载后 hooks 零残留 (运行中 Agent 同步清除) ─────────────


@pytest.mark.asyncio
async def test_uninstall_clears_running_agent_hooks() -> None:
    """卸载插件后运行中 Agent 的工具/命令按来源同步清除, 零残留。"""
    from isac.agent.tools.registry import ToolRegistry
    from isac.commands.registry import CommandRegistry
    from isac.plugin.runtime.activation import sync_plugin_tools_to_agents

    class _Tool:
        name = "plug_tool"
        description = "t"
        parameters: dict = {"type": "object", "properties": {}}

        async def execute(self, context: Any) -> Any:
            return None

    class _Instance:
        agent_id = "a1"
        status = "running"

        def __init__(self) -> None:
            self.tools = ToolRegistry()
            self.commands = CommandRegistry()
            self.prompt_builder = None

    class _AgentManager:
        def __init__(self, instances: list) -> None:
            self._instances = instances

        async def list(self) -> list:
            return self._instances

    shared_tools = ToolRegistry()
    shared_commands = CommandRegistry()
    shared_tools.register(_Tool(), source="plug_a")
    services = {"plugin_tools": shared_tools, "plugin_commands": shared_commands}
    instance = _Instance()
    agent_manager = _AgentManager([instance])

    # 安装: 同步到运行中 Agent → 工具可见 (U0 Fix-88: 插件来源工具自动命名空间化)
    await sync_plugin_tools_to_agents(agent_manager, services, "plug_a")
    assert instance.tools.get("plug_a:plug_tool") is not None

    # 卸载: 共享表按来源移除 + 再同步 → 运行中 Agent 零残留 (不留至重启)
    shared_tools.deregister_by_source("plug_a")
    await sync_plugin_tools_to_agents(agent_manager, services, "plug_a")
    assert instance.tools.get("plug_a:plug_tool") is None
    assert instance.tools.source_of("plug_a:plug_tool") is None
