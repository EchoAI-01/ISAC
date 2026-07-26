"""平台适配器模板骨架 (O4, DEVELOP.md 3.3)。

[框架已搭建 / scaffolding] 新增 IM 平台 (微信/Slack/飞书…) 的可复制模板: 实现
PlatformAdapter 的 4 个抽象方法。真正的连接/收发/媒体能力声明由各平台实现节点填充。

**此模板不自动注册** —— 仅作为新增适配器的起点; 复制到 adapters/<platform>/ 后
按 DEVELOP.md 3.3 实现并在 main.py 注册。默认不接入任何 Channel, 零行为变化。
"""

from __future__ import annotations

from isac.channel.base import PlatformAdapter
from isac.channel.model import ISACMessage
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class TemplateAdapter(PlatformAdapter):
    """新平台适配器模板 (复制后改名并实现)。"""

    def __init__(self, platform: str = "template") -> None:
        self._platform = platform

    @property
    def platform_name(self) -> str:
        return self._platform

    async def start(self) -> None:
        """建立平台连接并开始接收消息 (收到消息后调 self.on_message)。

        TODO(O4): 连接平台 (WebSocket/长轮询/Webhook), 把入站消息规范化为 ISACMessage
        后交给 self.on_message。骨架阶段 no-op (不连接)。
        """
        logger.debug("模板适配器 start (骨架 no-op)", platform=self._platform)

    async def stop(self) -> None:
        """断开连接并清理资源。TODO(O4): 关闭连接/取消后台任务。骨架 no-op。"""

    async def send(self, message: ISACMessage) -> bool:
        """把出站消息发送到平台。

        TODO(O4): 把 ISACMessage 的 segments 适配为平台消息格式并发送;
        骨架阶段返回 False (未实现)。
        """
        _ = message
        return False
