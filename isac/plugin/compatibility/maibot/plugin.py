"""MaiBot Plugin 基类映射 (ARCHITECTURE.md 3.8 兼容表)。

TODO(Day 56): MaiBot Plugin 基类 → ISACPlugin 包装；
MaiBot 插件配置 → Plugin Manifest config_schema。
"""

from __future__ import annotations

from typing import Any


class MaiBotPluginAdapter:
    """MaiBot Plugin → ISAC 包装器。"""

    def __init__(self, maibot_plugin: Any):
        self._plugin = maibot_plugin

    async def adapt(self) -> Any:
        raise NotImplementedError("TODO(Day 56): 实现 MaiBot Plugin 适配")
