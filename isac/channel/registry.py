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
        # N5b 批次G: 单个适配器启动失败不应中断其余平台 (此前裸 for + await, 任一
        # platform.start() 抛异常则后续平台全部不启动, 多平台部署下一个配置错即全停)。
        for adapter in self._adapters.values():
            logger.info("启动平台适配器", platform=adapter.platform_name)
            try:
                await adapter.start()
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "平台适配器启动失败, 跳过该平台 (其余继续)",
                    platform=adapter.platform_name, error=str(exc), exc_info=True,
                )

    async def stop_all(self) -> None:
        # N5b 批次G: 关闭同样需错误隔离 —— 一个适配器 stop() 抛异常不应阻止其余
        # 适配器关闭 (否则连接/子进程泄漏残留, 下次启动冲突)。
        for adapter in self._adapters.values():
            logger.info("停止平台适配器", platform=adapter.platform_name)
            try:
                await adapter.stop()
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "平台适配器停止失败, 继续停止其余",
                    platform=adapter.platform_name, error=str(exc), exc_info=True,
                )
