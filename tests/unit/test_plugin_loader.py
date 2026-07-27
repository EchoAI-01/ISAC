"""F4 PluginManager/PluginLoader 单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from isac.plugin.runtime.loader import PluginFormat, PluginLoader
from isac.plugin.runtime.manager import PluginManager


@pytest.fixture
def tmp_plugin_dir(tmp_path: Path) -> Path:
    """构造一个含三种格式插件的目录。"""
    plugins_root = tmp_path / "plugins"
    plugins_root.mkdir()

    # ISAC Native 插件
    native_dir = plugins_root / "native_hello"
    native_dir.mkdir()
    (native_dir / "manifest.jsonc").write_text(
        json.dumps(
            {
                "name": "native_hello",
                "version": "1.0.0",
                "description": "测试原生插件",
                "entry": "plugin.py",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (native_dir / "plugin.py").write_text(
        "from isac.plugin.native.plugin import ISACPlugin\n"
        "class HelloPlugin(ISACPlugin):\n"
        "    async def on_load(self, context):\n"
        "        self.context = context\n"
        "    async def on_unload(self):\n"
        "        self.unloaded = True\n",
        encoding="utf-8",
    )

    # AstrBot 插件
    astrbot_dir = plugins_root / "astrbot_hello"
    astrbot_dir.mkdir()
    (astrbot_dir / "metadata.yaml").write_text("name: astrbot_hello\n", encoding="utf-8")
    (astrbot_dir / "plugin.py").write_text(
        "from isac.plugin.compatibility.astrbot.star import Star\n"
        "class HelloStar(Star):\n"
        "    pass\n",
        encoding="utf-8",
    )

    # MaiBot 插件
    maibot_dir = plugins_root / "maibot_hello"
    maibot_dir.mkdir()
    (maibot_dir / "mai_plugin.yaml").write_text("name: maibot_hello\n", encoding="utf-8")
    (maibot_dir / "plugin.py").write_text(
        "from isac.plugin.compatibility.maibot.plugin import MaiBotPlugin\n"
        "class HelloMaiBot(MaiBotPlugin):\n"
        "    pass\n",
        encoding="utf-8",
    )

    return plugins_root


class TestPluginLoaderDetect:
    def test_detect_native(self, tmp_plugin_dir: Path) -> None:
        loader = PluginLoader()
        assert loader.detect_format(tmp_plugin_dir / "native_hello") == PluginFormat.ISAC_NATIVE

    def test_detect_astrbot(self, tmp_plugin_dir: Path) -> None:
        loader = PluginLoader()
        assert loader.detect_format(tmp_plugin_dir / "astrbot_hello") == PluginFormat.ASTRBOT

    def test_detect_maibot(self, tmp_plugin_dir: Path) -> None:
        loader = PluginLoader()
        assert loader.detect_format(tmp_plugin_dir / "maibot_hello") == PluginFormat.MAIBOT

    def test_detect_unknown_raises(self, tmp_path: Path) -> None:
        unknown_dir = tmp_path / "unknown"
        unknown_dir.mkdir()
        loader = PluginLoader()
        with pytest.raises(ValueError, match="无法识别"):
            loader.detect_format(unknown_dir)


class TestPluginLoaderLoad:
    @pytest.mark.asyncio
    async def test_load_native_finds_subclass(self, tmp_plugin_dir: Path) -> None:
        loader = PluginLoader()
        loaded = await loader.load(tmp_plugin_dir / "native_hello")
        assert loaded.is_native()
        assert loaded.name == "native_hello"
        assert loaded.manifest["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_load_astrbot_finds_star(self, tmp_plugin_dir: Path) -> None:
        loader = PluginLoader()
        loaded = await loader.load(tmp_plugin_dir / "astrbot_hello")
        assert loaded.is_astrbot()
        assert type(loaded.instance).__name__ == "HelloStar"

    @pytest.mark.asyncio
    async def test_load_maibot_finds_plugin(self, tmp_plugin_dir: Path) -> None:
        loader = PluginLoader()
        loaded = await loader.load(tmp_plugin_dir / "maibot_hello")
        assert loaded.is_maibot()
        assert type(loaded.instance).__name__ == "HelloMaiBot"


class TestPluginManagerLoadAll:
    @pytest.mark.asyncio
    async def test_load_all_loads_every_plugin(self, tmp_plugin_dir: Path) -> None:
        manager = PluginManager({})
        report = await manager.load_all(tmp_plugin_dir)
        assert "native_hello" in report
        assert "astrbot_hello" in report
        assert "maibot_hello" in report
        assert "loaded" in report["native_hello"]

    @pytest.mark.asyncio
    async def test_load_all_skips_nonexistent_dir(self, tmp_path: Path) -> None:
        manager = PluginManager({})
        report = await manager.load_all(tmp_path / "no_such_dir")
        assert report == {}

    @pytest.mark.asyncio
    async def test_load_all_isolates_failed_plugin(self, tmp_path: Path) -> None:
        plugins_root = tmp_path / "plugins"
        plugins_root.mkdir()
        # 一个坏插件 + 一个好插件
        bad_dir = plugins_root / "bad"
        bad_dir.mkdir()
        (bad_dir / "plugin.py").write_text("raise RuntimeError('bad plugin')", encoding="utf-8")
        good_dir = plugins_root / "good"
        good_dir.mkdir()
        (good_dir / "manifest.jsonc").write_text(
            json.dumps({"name": "good", "entry": "plugin.py"}), encoding="utf-8"
        )
        (good_dir / "plugin.py").write_text(
            "from isac.plugin.native.plugin import ISACPlugin\n"
            "class GoodPlugin(ISACPlugin):\n    pass\n",
            encoding="utf-8",
        )

        manager = PluginManager({})
        report = await manager.load_all(plugins_root)
        assert "failed" in report["bad"]
        assert "loaded" in report["good"]


class TestPluginManagerUnload:
    @pytest.mark.asyncio
    async def test_unload_calls_on_unload_and_removes(self, tmp_plugin_dir: Path) -> None:
        manager = PluginManager({})
        await manager.load_all(tmp_plugin_dir)
        loaded = manager.get("native_hello")
        assert loaded is not None
        result = await manager.unload("native_hello")
        assert result is True
        assert manager.get("native_hello") is None

    @pytest.mark.asyncio
    async def test_unload_unknown_returns_false(self) -> None:
        manager = PluginManager({})
        result = await manager.unload("not_exist")
        assert result is False


class TestPluginManagerIsolation:
    """H2: manifest isolated=true 的插件经 PluginIsolationHost 在子进程加载并可 IPC 调用。"""

    @staticmethod
    def _make_isolated_plugin(root: Path, name: str = "iso_hello") -> None:
        plugin_dir = root / name
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "manifest.jsonc").write_text(
            json.dumps({"name": name, "version": "1.0.0", "entry": "plugin.py", "isolated": True}),
            encoding="utf-8",
        )
        (plugin_dir / "plugin.py").write_text(
            "from isac.plugin.native.plugin import ISACPlugin\n"
            "class IsoPlugin(ISACPlugin):\n"
            "    def ping(self):\n"
            "        return 'pong'\n",
            encoding="utf-8",
        )

    @pytest.mark.asyncio
    async def test_isolated_plugin_loads_in_subprocess(self, tmp_path: Path) -> None:
        root = tmp_path / "plugins"
        root.mkdir()
        self._make_isolated_plugin(root)
        manager = PluginManager({})
        try:
            report = await manager.load_all(root)
            assert report["iso_hello"] == "loaded (isolated)"
            assert manager.is_isolated("iso_hello") is True
            # 隔离插件不在宿主进程内 loader 里 (get 从 _loaded 取)
            assert manager.get("iso_hello") is None
            # 子进程真实加载了插件, 可经 IPC 调用其方法
            assert await manager.call_isolated("iso_hello", "ping") == "pong"
        finally:
            await manager.shutdown()

    @pytest.mark.asyncio
    async def test_non_isolated_plugin_still_loads_in_process(self, tmp_path: Path) -> None:
        root = tmp_path / "plugins"
        root.mkdir()
        plugin_dir = root / "plain"
        plugin_dir.mkdir()
        (plugin_dir / "manifest.jsonc").write_text(
            json.dumps({"name": "plain", "entry": "plugin.py"}), encoding="utf-8"
        )
        (plugin_dir / "plugin.py").write_text(
            "from isac.plugin.native.plugin import ISACPlugin\nclass PlainPlugin(ISACPlugin):\n    pass\n",
            encoding="utf-8",
        )
        manager = PluginManager({})
        await manager.load_all(root)
        assert manager.is_isolated("plain") is False
        assert manager.get("plain") is not None  # 内进程加载

    @pytest.mark.asyncio
    async def test_unload_isolated_kills_host(self, tmp_path: Path) -> None:
        root = tmp_path / "plugins"
        root.mkdir()
        self._make_isolated_plugin(root)
        manager = PluginManager({})
        await manager.load_all(root)
        assert manager.is_isolated("iso_hello") is True
        assert await manager.unload("iso_hello") is True
        assert manager.is_isolated("iso_hello") is False
