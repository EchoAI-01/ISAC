"""#28 (tools M12): AstrBot 兼容层 import 重定向接线。

此前 install_sandbox 全仓零调用 —— 真实 AstrBot 插件 (plugin.py 内
``from astrbot.api.star import Star``) 在 exec_module 时 ImportError, 兼容层
对其目标生态实际不可用; 既有测试全部直接 import ISAC 侧 shim, 未覆盖真实插件。

验收:
- loader 加载"真实 AstrBot 插件" (plugin.py 用 astrbot.* import) 成功;
- import 重定向到 ISAC 兼容层 (Star 子类被识别);
- install_sandbox 幂等 (重复调用不堆叠 finder);
- 父包 astrbot/astrbot.api 可解析 (空命名空间包);
- 未映射的 astrbot.* 子模块明确 ImportError (fail-fast 不静默)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from isac.plugin.compatibility.astrbot.sandbox import (
    AstrBotImportFinder,
    install_sandbox,
)
from isac.plugin.compatibility.astrbot.star import Star
from isac.plugin.runtime.loader import PluginFormat, PluginLoader


@pytest.fixture
def sandbox_installed() -> None:
    """测试后清理 meta_path 里的 finder + 被重定向的 astrbot.* 模块缓存。"""
    yield
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, AstrBotImportFinder)]
    for name in [n for n in sys.modules if n == "astrbot" or n.startswith("astrbot.")]:
        sys.modules.pop(name, None)


def _write_real_astrbot_plugin(plugin_dir: Path) -> None:
    """写一个'真实 AstrBot 插件': metadata.yaml 入口特征 + plugin.py 用 astrbot.* import。"""
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "metadata.yaml").write_text("name: myreal\n", encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        "from astrbot.api.star import Star\n"
        "\n"
        "\n"
        "class MyRealPlugin(Star):\n"
        "    pass\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_load_real_astrbot_plugin(tmp_path: Path, sandbox_installed: None) -> None:
    """M12 核心验收: plugin.py 用 astrbot.* import 的真实插件可被 loader 加载。"""
    plugin_dir = tmp_path / "myreal"
    _write_real_astrbot_plugin(plugin_dir)
    loader = PluginLoader()
    loaded = await loader.load(plugin_dir)
    assert loaded.format == PluginFormat.ASTRBOT
    assert isinstance(loaded.instance, Star)  # 重定向后 Star 子类被识别
    assert loaded.name == "MyRealPlugin"


@pytest.mark.asyncio
async def test_load_real_astrbot_plugin_with_event_import(
    tmp_path: Path, sandbox_installed: None
) -> None:
    """同时 import astrbot.api.event (多映射模块)。"""
    plugin_dir = tmp_path / "multimod"
    plugin_dir.mkdir()
    (plugin_dir / "metadata.yaml").write_text("name: multimod\n", encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        "from astrbot.api.star import Star\n"
        "from astrbot.api.event import AstrBotEventType\n"
        "\n"
        "\n"
        "class EventPlugin(Star):\n"
        "    pass\n",
        encoding="utf-8",
    )
    loader = PluginLoader()
    loaded = await loader.load(plugin_dir)
    assert loaded.format == PluginFormat.ASTRBOT
    assert isinstance(loaded.instance, Star)


def test_install_sandbox_idempotent(sandbox_installed: None) -> None:
    install_sandbox()
    install_sandbox()
    install_sandbox()
    finders = [f for f in sys.meta_path if isinstance(f, AstrBotImportFinder)]
    assert len(finders) == 1


def test_parent_packages_resolvable(sandbox_installed: None) -> None:
    """import astrbot / astrbot.api 父包可解析 (空命名空间包, 不 ModuleNotFoundError)。"""
    install_sandbox()
    import astrbot  # noqa: F401
    import astrbot.api  # noqa: F401


def test_redirected_module_is_compat_layer(sandbox_installed: None) -> None:
    """astrbot.api.star 解析到 ISAC 兼容层模块 (同一对象)。"""
    install_sandbox()
    import astrbot.api.star as redirected

    from isac.plugin.compatibility.astrbot import star as compat

    assert redirected is compat
    assert redirected.Star is Star


def test_unmapped_astrbot_module_raises(sandbox_installed: None) -> None:
    """未映射的 astrbot.* 子模块明确 ImportError (fail-fast, 不静默降级)。"""
    install_sandbox()
    with pytest.raises(ImportError, match="不支持的 astrbot 模块"):
        import astrbot.core.something_deep  # noqa: F401
