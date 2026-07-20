"""平台适配器注册表。

Channel 连接是共享资源 (ADR-008): 注册表管理连接生命周期，
Agent 与连接的绑定关系由 MessageRouter 规则决定，不在此处。
"""

from __future__ import annotations

from isac.channel.base import PlatformAdapter
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class ChannelRegistry:
    """管理所有平台适配器的注册与生命周期。"""

    def __init__(self) -> None:
        self._adapters: dict[str, PlatformAdapter] = {}

    def register(self, adapter: PlatformAdapter) -> None:
        """注册适配器（以 platform_name 为键，重复注册覆盖并告警）。"""
        if adapter.platform_name in self._adapters:
            logger.warning("平台适配器重复注册，已覆盖", platform=adapter.platform_name)
        self._adapters[adapter.platform_name] = adapter

    def get(self, platform: str) -> PlatformAdapter | None:
        return self._adapters.get(platform)

    def list(self) -> list[PlatformAdapter]:
        return list(self._adapters.values())

    async def start_all(self) -> None:
        for adapter in self._adapters.values():
            logger.info("启动平台适配器", platform=adapter.platform_name)
            await adapter.start()

    async def stop_all(self) -> None:
        for adapter in self._adapters.values():
            logger.info("停止平台适配器", platform=adapter.platform_name)
            await adapter.stop()
