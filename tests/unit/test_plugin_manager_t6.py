"""T6 PluginManager 扩展测试: install/reload/uninstall/failures/retry。

用真实插件目录 (manifest.jsonc + plugin.py 含 ISACPlugin 子类) 驱动 PluginLoader;
installer 用桩或真实目录构造。隔离插件 reload 需子进程, 此处不覆盖 (架构债)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from isac.plugin.runtime.manager import PluginManager


def _make_native_plugin(parent: Path, name: str) -> Path:
    """在 parent 下创建一个最小 ISAC 原生插件目录, 返回插件目录路径。"""
    pdir = parent / name
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "manifest.jsonc").write_text(f'{{"name":"{name}","entry":"plugin.py"}}')
    (pdir / "plugin.py").write_text(
        "from isac.plugin.native.plugin import ISACPlugin\n"
        f"class {name.capitalize()}(ISACPlugin):\n"
        "    pass\n"
    )
    return pdir


@pytest.mark.asyncio
async def test_reload_native(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    _make_native_plugin(plugins_dir, "myplug")
    pm = PluginManager({})
    await pm.load_all(plugins_dir)
    assert "myplug" in pm.list_loaded()

    status = await pm.reload("myplug")
    assert "loaded" in status
    assert "myplug" in pm.list_loaded()


@pytest.mark.asyncio
async def test_reload_not_loaded() -> None:
    pm = PluginManager({})
    status = await pm.reload("nope")
    assert status == "not_loaded"


@pytest.mark.asyncio
async def test_install_loads(tmp_path: Path) -> None:
    pm = PluginManager({})
    pm._plugins_dir = tmp_path

    class _FakeInstaller:
        async def install(self, source: dict) -> Path:
            return _make_native_plugin(tmp_path, "newplug")

    status = await pm.install({"type": "market", "name": "newplug"}, _FakeInstaller())
    assert "loaded" in status
    assert "newplug" in pm.list_loaded()


@pytest.mark.asyncio
async def test_uninstall_removes_dir(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    _make_native_plugin(plugins_dir, "myplug")
    pm = PluginManager({})
    pm._plugins_dir = plugins_dir
    await pm.load_all(plugins_dir)
    assert "myplug" in pm.list_loaded()

    status = await pm.uninstall("myplug")
    assert status == "uninstalled"
    assert not (plugins_dir / "myplug").exists()
    assert "myplug" not in pm.list_loaded()


@pytest.mark.asyncio
async def test_list_failures(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    bad = plugins_dir / "badplug"
    bad.mkdir(parents=True)
    (bad / "readme.txt").write_text("not a plugin")  # 无入口特征
    pm = PluginManager({})
    await pm.load_all(plugins_dir)
    failures = pm.list_failures()
    assert "badplug" in failures


@pytest.mark.asyncio
async def test_retry_success(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    bad = plugins_dir / "retryplug"
    bad.mkdir(parents=True)
    (bad / "readme.txt").write_text("not a plugin")
    pm = PluginManager({})
    pm._plugins_dir = plugins_dir
    await pm.load_all(plugins_dir)
    assert "retryplug" in pm.list_failures()

    # 修复: 补入口
    (bad / "manifest.jsonc").write_text('{"name":"retryplug","entry":"plugin.py"}')
    (bad / "plugin.py").write_text(
        "from isac.plugin.native.plugin import ISACPlugin\n"
        "class Retryplug(ISACPlugin):\n"
        "    pass\n"
    )
    status = await pm.retry("retryplug")
    assert "loaded" in status
    assert "retryplug" not in pm.list_failures()
