"""OneBot v11 平台适配器。

决策点 (DEVELOPMENT_PLAN.md): OneBot v11 (aiocqhttp)，生态更成熟。
联调准备: NapCat + 测试 QQ 号 + 测试群 (DEVELOPMENT_PLAN.md 准备清单)。
"""

from __future__ import annotations

from typing import Any

from isac.channel.base import PlatformAdapter
from isac.channel.model import ISACMessage


class OneBotAdapter(PlatformAdapter):
    """OneBot v11 适配器 (WebSocket)。

    TODO(Day 3-4):
    - 基于 aiocqhttp 建立 WS 连接 (config 中读取 ws_url/access_token)
    - OneBot 消息 → ISACMessage 转换 (text/at/image/reply segments)
    - ISACMessage → OneBot 消息段发送
    - 重连机制 (PlatformError, 见 SPECIFICATION.md 5.1)
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @property
    def platform_name(self) -> str:
        return "qq"

    async def start(self) -> None:
        raise NotImplementedError("TODO(Day 3): 建立 OneBot WebSocket 连接")

    async def stop(self) -> None:
        raise NotImplementedError("TODO(Day 3): 断开连接并清理资源")

    async def send(self, message: ISACMessage) -> bool:
        raise NotImplementedError("TODO(Day 4): ISACMessage → OneBot 消息段发送")
