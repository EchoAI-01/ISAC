"""T6 routes 端点测试: marketplace/install/reload/uninstall/failed/retry。

用 TestClient + build_plugin_marketplace_router 直接构造 router (不经
create_control_app, 无 auth/scope, 聚焦端点编排 + allow_install)。setup 用
asyncio.run 处理 PluginManager 异步加载, 避免与 TestClient event loop 冲突。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from isac.agent.tools.registry import ToolRegistry
from isac.control.api.routes_plugins import build_plugin_marketplace_router
from isac.plugin.runtime.installer import PluginInstaller
from isac.plugin.runtime.manager import PluginManager


class _FakeAgent:
    def __init__(self, agent_id: str = "a1") -> None:
        self.agent_id = agent_id
        self.status = "running"
        self.tools = ToolRegistry()
        self.commands: Any = None
        self.prompt_builder: Any = None


class _FakeAgentManager:
    def __init__(self, agents: list[_FakeAgent]) -> None:
        self._agents = agents

    async def list(self) -> list[_FakeAgent]:
        return self._agents


def _native_plugin(parent: Path, name: str) -> Path:
    pdir = parent / name
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "manifest.jsonc").write_text(f'{{"name":"{name}","entry":"plugin.py"}}')
    (pdir / "plugin.py").write_text(
        "from isac.plugin.native.plugin import ISACPlugin\n"
        f"class {name.capitalize()}(ISACPlugin):\n"
        "    pass\n"
    )
    return pdir


def _make_app(
    pm: PluginManager, am: _FakeAgentManager, installer: Any, services: dict,
    *, event_bus: Any = None, allow_install: bool = True,
) -> Any:
    from fastapi import FastAPI

    app = FastAPI()
    router = build_plugin_marketplace_router(
        pm, am, installer, services, event_bus=event_bus, allow_install=allow_install
    )
    app.include_router(router, prefix="/api/v1")
    return app


def _client(app: Any) -> Any:
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_marketplace_endpoint(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    mp = tmp_path / "market.jsonc"
    mp.write_text('{"plugins":[{"name":"x","version":"1"}]}')
    pm = PluginManager({})
    installer = PluginInstaller(plugins_dir=plugins_dir, marketplace_local_path=mp)
    app = _make_app(pm, _FakeAgentManager([]), installer, {})
    resp = _client(app).get("/api/v1/plugins/marketplace")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["plugins"][0]["name"] == "x"


def test_failed_endpoint(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    bad = plugins_dir / "badplug"
    bad.mkdir(parents=True)
    (bad / "readme.txt").write_text("x")
    pm = PluginManager({})
    asyncio.run(pm.load_all(plugins_dir))
    installer = PluginInstaller(plugins_dir=plugins_dir)
    app = _make_app(pm, _FakeAgentManager([]), installer, {})
    resp = _client(app).get("/api/v1/plugins/failed")
    assert resp.status_code == 200
    assert "badplug" in resp.json()["failures"]


def test_install_endpoint(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"

    class _FakeInstaller:
        async def install(self, source: dict) -> Path:
            return _native_plugin(plugins_dir, source["name"])

        async def load_marketplace(self, *, refresh: bool = False) -> list[dict]:
            return []

    pm = PluginManager({})
    pm._plugins_dir = plugins_dir
    installer = _FakeInstaller()
    services: dict = {"event_bus": object()}
    agent = _FakeAgent()
    app = _make_app(pm, _FakeAgentManager([agent]), installer, services, event_bus=services["event_bus"])
    resp = _client(app).post(
        "/api/v1/plugins/install", json={"source": {"type": "market", "name": "smokeplug"}}
    )
    assert resp.status_code == 200
    assert "loaded" in resp.json()["status"]
    assert "smokeplug" in pm.list_loaded()


def test_reload_endpoint(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    _native_plugin(plugins_dir, "myplug")
    pm = PluginManager({})
    pm._plugins_dir = plugins_dir
    asyncio.run(pm.load_all(plugins_dir))
    installer = PluginInstaller(plugins_dir=plugins_dir)
    services: dict = {"event_bus": object()}
    app = _make_app(
        pm, _FakeAgentManager([_FakeAgent()]), installer, services, event_bus=services["event_bus"]
    )
    resp = _client(app).post("/api/v1/plugins/myplug/reload")
    assert resp.status_code == 200
    assert "loaded" in resp.json()["status"]


def test_uninstall_endpoint(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    _native_plugin(plugins_dir, "myplug")
    pm = PluginManager({})
    pm._plugins_dir = plugins_dir
    asyncio.run(pm.load_all(plugins_dir))
    installer = PluginInstaller(plugins_dir=plugins_dir)
    app = _make_app(pm, _FakeAgentManager([]), installer, {"event_bus": object()})
    resp = _client(app).delete("/api/v1/plugins/myplug")
    assert resp.status_code == 200
    assert resp.json()["status"] == "uninstalled"
    assert not (plugins_dir / "myplug").exists()


def test_retry_endpoint(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    bad = plugins_dir / "retryplug"
    bad.mkdir(parents=True)
    (bad / "readme.txt").write_text("x")
    pm = PluginManager({})
    pm._plugins_dir = plugins_dir
    asyncio.run(pm.load_all(plugins_dir))
    # 修复入口
    (bad / "manifest.jsonc").write_text('{"name":"retryplug","entry":"plugin.py"}')
    (bad / "plugin.py").write_text(
        "from isac.plugin.native.plugin import ISACPlugin\n"
        "class Retryplug(ISACPlugin):\n"
        "    pass\n"
    )
    installer = PluginInstaller(plugins_dir=plugins_dir)
    app = _make_app(
        pm, _FakeAgentManager([]), installer, {"event_bus": object()}, event_bus=object()
    )
    resp = _client(app).post("/api/v1/plugins/retryplug/retry")
    assert resp.status_code == 200
    assert "loaded" in resp.json()["status"]


def test_allow_install_false_hides_write_endpoints(tmp_path: Path) -> None:
    pm = PluginManager({})
    installer = PluginInstaller(plugins_dir=tmp_path / "plugins")
    app = _make_app(pm, _FakeAgentManager([]), installer, {}, allow_install=False)
    client = _client(app)
    # 写端点未注册 → 404
    resp = client.post("/api/v1/plugins/install", json={"source": {"type": "market", "name": "x"}})
    assert resp.status_code == 404
    # 读端点仍在
    assert client.get("/api/v1/plugins/marketplace").status_code == 200
