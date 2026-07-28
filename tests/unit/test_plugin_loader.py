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


class TestPluginManagerDeployerForcedIsolation:
    """Fix-31: 部署方经 isolated_plugins 配置强制隔离, 不依赖插件自己的 manifest 声明。"""

    @staticmethod
    def _make_plain_native_plugin(root: Path, name: str) -> None:
        """未声明 isolated 字段的普通原生插件 (manifest 里没有 isolated: true)。"""
        plugin_dir = root / name
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "manifest.jsonc").write_text(
            json.dumps({"name": name, "version": "1.0.0", "entry": "plugin.py"}),
            encoding="utf-8",
        )
        (plugin_dir / "plugin.py").write_text(
            "from isac.plugin.native.plugin import ISACPlugin\n"
            "class PlainPlugin(ISACPlugin):\n"
            "    def ping(self):\n"
            "        return 'pong'\n",
            encoding="utf-8",
        )

    @pytest.mark.asyncio
    async def test_deployer_forced_isolation_by_name_overrides_manifest(self, tmp_path: Path) -> None:
        """插件 manifest 没有 isolated: true, 但部署方按目录名强制隔离 —— 仍应隔离加载。"""
        root = tmp_path / "plugins"
        root.mkdir()
        self._make_plain_native_plugin(root, "untrusted_plugin")
        manager = PluginManager({"isolated_plugins": ["untrusted_plugin"]})
        try:
            report = await manager.load_all(root)
            assert report["untrusted_plugin"] == "loaded (isolated)"
            assert manager.is_isolated("untrusted_plugin") is True
        finally:
            await manager.shutdown()

    @pytest.mark.asyncio
    async def test_deployer_forced_isolation_does_not_affect_unlisted_plugin(
        self, tmp_path: Path
    ) -> None:
        """isolated_plugins 只对列出的目录名生效, 未列出的插件维持原有 (宿主进程内) 行为。"""
        root = tmp_path / "plugins"
        root.mkdir()
        self._make_plain_native_plugin(root, "untrusted_plugin")
        self._make_plain_native_plugin(root, "trusted_plugin")
        manager = PluginManager({"isolated_plugins": ["untrusted_plugin"]})
        try:
            await manager.load_all(root)
            assert manager.is_isolated("untrusted_plugin") is True
            assert manager.is_isolated("trusted_plugin") is False
            assert manager.get("trusted_plugin") is not None
        finally:
            await manager.shutdown()

    @pytest.mark.asyncio
    async def test_wildcard_isolated_plugins_forces_all(self, tmp_path: Path) -> None:
        """isolated_plugins: "*" 强制隔离该加载路径下全部插件, 无需逐个列出目录名。"""
        root = tmp_path / "plugins"
        root.mkdir()
        self._make_plain_native_plugin(root, "plugin_a")
        self._make_plain_native_plugin(root, "plugin_b")
        manager = PluginManager({"isolated_plugins": "*"})
        try:
            await manager.load_all(root)
            assert manager.is_isolated("plugin_a") is True
            assert manager.is_isolated("plugin_b") is True
        finally:
            await manager.shutdown()

    @pytest.mark.asyncio
    async def test_absent_isolated_plugins_config_defaults_to_no_forced_isolation(
        self, tmp_path: Path
    ) -> None:
        """未配置 isolated_plugins (如 PluginManager({})) 时零行为变化: 仍只按 manifest 决定。"""
        root = tmp_path / "plugins"
        root.mkdir()
        self._make_plain_native_plugin(root, "plain")
        manager = PluginManager({})
        await manager.load_all(root)
        assert manager.is_isolated("plain") is False
        assert manager.get("plain") is not None

    @pytest.mark.asyncio
    async def test_forced_isolation_on_non_native_plugin_fails_clearly_instead_of_unprotected_load(
        self, tmp_path: Path
    ) -> None:
        """AstrBot/MaiBot 兼容层插件没有 manifest.jsonc, 隔离机制目前无法真正隔离它——
        部署方强制隔离时必须显式失败 (清晰错误信息), 不能静默退回不受保护的宿主进程内加载。"""
        root = tmp_path / "plugins"
        root.mkdir()
        astrbot_dir = root / "astrbot_untrusted"
        astrbot_dir.mkdir()
        (astrbot_dir / "metadata.yaml").write_text("name: astrbot_untrusted\n", encoding="utf-8")
        (astrbot_dir / "plugin.py").write_text(
            "from isac.plugin.compatibility.astrbot.star import Star\n"
            "class UntrustedStar(Star):\n"
            "    pass\n",
            encoding="utf-8",
        )
        manager = PluginManager({"isolated_plugins": ["astrbot_untrusted"]})
        report = await manager.load_all(root)
        assert report["astrbot_untrusted"].startswith("failed:")
        assert "manifest.jsonc" in report["astrbot_untrusted"]
        # 失败即拒绝, 绝不能悄悄退回宿主进程内加载 (那样就等于隔离形同虚设)。
        assert manager.get("astrbot_untrusted") is None
        assert manager.is_isolated("astrbot_untrusted") is False
