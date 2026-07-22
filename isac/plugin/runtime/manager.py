"""PluginManager: 插件生命周期管理。"""

from __future__ import annotations

from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)


class PluginManager:
    """插件管理器。

    [桩] 待实现:
    - 加载/依赖解析/热重载; 插件错误隔离 (SPECIFICATION.md 5.1)
    - 启用矩阵生效 (AgentConfig.plugins_allow/deny ∩ channel_matrix)
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._plugins: dict[str, Any] = {}

    async def load_all(self, plugin_dir: str) -> None:
        """加载目录下全部插件 (自动识别 AstrBot / MaiBot / ISAC 原生格式)。"""
        raise NotImplementedError("PluginManager.load_all 尚未实现")

    async def unload(self, name: str) -> None:
        raise NotImplementedError("PluginManager.unload 尚未实现")

    def is_enabled_for(self, plugin_name: str, agent_id: str, platform: str) -> bool:
        """启用矩阵检查: Agent 允许 ∩ Channel 允许。"""
        # TODO: 实现有效权限计算
        return True
