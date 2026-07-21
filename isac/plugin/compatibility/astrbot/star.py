"""AstrBot Star 基类兼容 (SPECIFICATION.md 2.7)。"""

from __future__ import annotations

from typing import Any


class Star:
    """兼容 astrbot.api.star.Star"""

    def __init__(self, context: Any):
        self.context = context

    async def terminate(self) -> None:
        """插件卸载时调用"""


class StarContext:
    """兼容 AstrBot Context 对象。

    TODO(Day 48-49): send_message/get_platform/get_provider 映射到 ISAC。
    """

    async def send_message(self, message: str, platform: str | None = None) -> None:
        raise NotImplementedError("TODO(Day 48): 映射到 ISAC Channel 发送")

    def get_platform(self, platform_name: str) -> Any | None:
        raise NotImplementedError("TODO(Day 48): 映射到 ChannelRegistry.get")

    def get_provider(self, provider_name: str | None = None) -> Any | None:
        raise NotImplementedError("TODO(Day 48): 映射到 ProviderManager")
