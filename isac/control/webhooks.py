"""Webhooks: 事件推送与自动化触发器 (ARCHITECTURE.md 3.9 / SPECIFICATION.md 4.4)。

事件类型: message.received / message.responded / agent.created /
         agent.stopped / inter_agent.sent

机制:
- subscribe(event, url) 订阅事件
- dispatch(event, data) 并发 POST 推送到所有订阅 URL, 失败重试 3 次
- /automation/trigger 入口供外部触发自定义事件
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 重试配置
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = 1.0  # 秒
DEFAULT_TIMEOUT = 10.0  # 秒


class WebhookManager:
    """Webhook 订阅与事件推送。

    [桩] 真实 httpx POST + 重试 + /automation/trigger 自动化入口。
    设计: 不依赖 httpx 同步阻塞, 用 asyncio.to_thread 包装。
    """

    def __init__(
        self,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff: float = DEFAULT_RETRY_BACKOFF,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: Any = None,
    ) -> None:
        self._subscriptions: dict[str, list[str]] = {}  # event -> [url, ...]
        self.max_retries = max(1, max_retries)
        self.retry_backoff = max(0.1, retry_backoff)
        self.timeout = max(1.0, timeout)
        # http_client 可注入 (测试时用 mock), 生产时用 httpx.AsyncClient
        self._http_client = http_client

    def subscribe(self, event: str, url: str) -> None:
        """订阅事件 → URL。"""
        self._subscriptions.setdefault(event, []).append(url)
        logger.info("Webhook 已订阅", event_name=event, url=url)

    def unsubscribe(self, event: str, url: str) -> None:
        """取消订阅。"""
        urls = self._subscriptions.get(event, [])
        if url in urls:
            urls.remove(url)
            logger.info("Webhook 已取消订阅", event_name=event, url=url)

    def list_subscriptions(self, event: str | None = None) -> dict[str, list[str]]:
        """列出订阅清单 (event=None 返回全部)。"""
        if event is None:
            return {e: list(urls) for e, urls in self._subscriptions.items()}
        return {event: list(self._subscriptions.get(event, []))}

    async def dispatch(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        """向所有订阅者推送事件。失败记录日志, 不影响主流程。

        返回 {url: "ok"/"failed: <error>"} 报告。
        """
        urls = self._subscriptions.get(event, [])
        if not urls:
            return {}
        tasks = [self._dispatch_one(url, event, data) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return dict(zip(urls, results, strict=False))

    async def trigger(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        """自动化触发入口 (/automation/trigger 调用)。

        与 dispatch 区别: trigger 是外部主动触发, 会触发事件 → 推送到所有订阅者。
        """
        logger.info("Webhook 外部触发", event_name=event)
        return await self.dispatch(event, data)

    async def _dispatch_one(self, url: str, event: str, data: dict[str, Any]) -> str:
        """向单个 URL 推送, 带重试。返回 "ok" 或 "failed: <error>"。"""
        payload = json.dumps({"event": event, "data": data}, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                success = await self._post(url, payload)
                if success:
                    return "ok"
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "Webhook 推送失败, 准备重试",
                    url=url,
                    attempt=attempt + 1,
                    error=str(exc),
                )
            if attempt < self.max_retries - 1:
                await asyncio.sleep(self.retry_backoff * (2**attempt))
        return f"failed: {last_error}" if last_error else "failed: unknown"

    async def _post(self, url: str, payload: bytes) -> bool:
        """真实 HTTP POST (httpx 注入时) 或 mock 返回。"""
        if self._http_client is not None:
            return await self._http_client.post(url, payload)
        # 默认: 尝试用 httpx (惰性导入)
        try:
            import httpx
        except ImportError:
            logger.warning("httpx 未安装, Webhook 推送跳过")
            return False
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    content=payload,
                    headers={"Content-Type": "application/json"},
                )
                return 200 <= response.status_code < 300
        except Exception as exc:  # noqa: BLE001
            logger.warning("Webhook HTTP POST 异常", url=url, error=str(exc))
            raise
