"""PluginManager: 插件生命周期管理。

加载目录下所有插件, 自动识别格式 (ISAC Native / AstrBot / MaiBot),
实例化后调用 on_load。热重载: 卸载时调用 on_unload 并从 Registry 移除。
错误隔离: 单个插件加载失败不影响其他插件。
启用矩阵: is_enabled_for 调用 EnableMatrix (Agent ∩ Channel ∩ 全局)。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from isac.plugin.runtime.loader import LoadedPlugin, PluginLoader
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.core.policy import EnableMatrix
    from isac.plugin.native.plugin import PluginContext

logger = get_logger(__name__)


class PluginManager:
    """插件管理器。

    待实现:
    - 加载/依赖解析/热重载; 插件错误隔离 (SPECIFICATION.md 5.1)
    - 启用矩阵生效 (AgentConfig.plugins_allow/deny ∩ channel_matrix)
    """

    def __init__(
        self,
        config: dict[str, Any],
        enable_matrix: EnableMatrix | None = None,
        plugin_context_factory: Any = None,
    ):
        self.config = config
        self.enable_matrix = enable_matrix
        self._loader = PluginLoader()
        self._loaded: dict[str, LoadedPlugin] = {}  # name -> LoadedPlugin
        self._plugin_context_factory = plugin_context_factory

    async def load_all(self, plugin_dir: str | Path) -> dict[str, Any]:
        """加载目录下全部插件 (自动识别 AstrBot / MaiBot / ISAC 原生格式)。

        错误隔离: 单个插件加载失败记录日志, 不影响其他插件。
        返回 {name: "loaded"/"failed: <error>"} 报告。
        """
        plugin_dir = Path(plugin_dir)
        if not plugin_dir.exists():
            logger.info("插件目录不存在, 跳过加载", plugin_dir=str(plugin_dir))
            return {}
        report: dict[str, str] = {}
        for entry in sorted(plugin_dir.iterdir()):
            if not entry.is_dir():
                continue
            try:
                loaded = await self._loader.load(entry)
                self._loaded[loaded.name] = loaded
                # report 用目录名作 key, 与 instance 类名/manifest.name 解耦
                report[entry.name] = f"loaded ({loaded.format.value})"
                logger.info("插件已加载", name=loaded.name, format=loaded.format.value, path=str(entry))
            except Exception as exc:  # noqa: BLE001 错误隔离
                logger.warning("插件加载失败", path=str(entry), error=str(exc))
                report[entry.name] = f"failed: {exc}"
        return report

    async def unload(self, name: str) -> bool:
        """卸载插件: 调用 on_unload 并从已加载列表移除。"""
        loaded = self._loaded.get(name)
        if loaded is None:
            return False
        try:
            if hasattr(loaded.instance, "on_unload"):
                await loaded.instance.on_unload()
        except Exception as exc:  # noqa: BLE001
            logger.warning("插件 on_unload 失败", name=name, error=str(exc))
        del self._loaded[name]
        logger.info("插件已卸载", name=name)
        return True

    def list_loaded(self) -> list[str]:
        return list(self._loaded.keys())

    def get(self, name: str) -> LoadedPlugin | None:
        return self._loaded.get(name)

    def is_enabled_for(self, plugin_name: str, agent_id: str, platform: str) -> bool:
        """启用矩阵检查: Agent 允许 ∩ Channel 允许。

        EnableMatrix 未注入时默认放行; 否则按 plugins_allow/deny + Channel 矩阵计算。
        """
        if self.enable_matrix is None:
            return True
        # Agent 的 plugins_allow/deny 由调用方提供, 这里退化为 "*" + []
        # 真实场景: 调用方应基于 AgentConfig.is_enabled_for 调用, 见 E4 测试。
        return self.enable_matrix.is_plugin_enabled(plugin_name, ["*"], [], agent_id=agent_id, platform=platform)

    async def call_on_load(self, context: PluginContext) -> dict[str, str]:
        """对每个已加载的 Native 插件调用 on_load (传入 PluginContext)。

        AstrBot/MaiBot 兼容层由适配器单独处理, 不在此调用。
        """
        report: dict[str, str] = {}
        for name, loaded in list(self._loaded.items()):
            if not loaded.is_native():
                continue
            try:
                if hasattr(loaded.instance, "on_load"):
                    await loaded.instance.on_load(context)
                report[name] = "on_load ok"
            except Exception as exc:  # noqa: BLE001 错误隔离
                logger.warning("插件 on_load 失败", name=name, error=str(exc))
                report[name] = f"failed: {exc}"
        return report
