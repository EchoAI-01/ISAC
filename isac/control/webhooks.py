"""Webhooks: 事件推送与自动化触发 (ARCHITECTURE.md 3.9 / SPECIFICATION.md 4.4)。

事件类型: message.received / message.responded / agent.created /
         agent.stopped / inter_agent.sent
"""

from __future__ import annotations

from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)


class WebhookManager:
    """Webhook 订阅与事件推送。

    TODO(Day 74): httpx POST 推送 + 重试 + /automation/trigger 自动化入口。
    """

    def __init__(self) -> None:
        self._subscriptions: dict[str, list[str]] = {}  # event -> [url, ...]

    def subscribe(self, event: str, url: str) -> None:
        self._subscriptions.setdefault(event, []).append(url)
        logger.info("Webhook 已订阅", event=event, url=url)

    def unsubscribe(self, event: str, url: str) -> None:
        urls = self._subscriptions.get(event, [])
        if url in urls:
            urls.remove(url)

    async def dispatch(self, event: str, data: dict[str, Any]) -> None:
        """向所有订阅者推送事件。失败记录日志，不影响主流程。"""
        for url in self._subscriptions.get(event, []):
            # TODO(Day 74): httpx POST + 重试
            logger.debug("Webhook 推送 (TODO)", event=event, url=url)
