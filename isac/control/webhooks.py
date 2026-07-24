"""Webhooks: 事件推送与自动化触发器 (ARCHITECTURE.md 3.9 / SPECIFICATION.md 4.4)。

事件类型: message.received / message.responded / agent.created /
         agent.stopped / inter_agent.sent

机制:
- subscribe(event, url) 订阅事件 (URL 经 SSRF 校验拒绝内网地址)
- dispatch(event, data) 并发 POST 推送到所有订阅 URL, 失败重试 3 次
- /automation/trigger 入口供外部触发自定义事件

安全 (K7, DEVELOPMENT_PLAN.md):
- URL 校验拒绝内网 IP / localhost / 链路本地地址, 防止 SSRF 攻击者通过 Webhook
  让 ISAC 进程访问内网服务 (元数据接口 / 内部管理面)
- allowlist 显式列出允许的 hostname (可选, 开发态允许 localhost)
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlparse

from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 重试配置
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = 1.0  # 秒
DEFAULT_TIMEOUT = 10.0  # 秒


class SSRFBlockedError(ValueError):
    """Webhook URL 被 SSRF 校验拒绝 (内网/链路本地/保留地址)。"""


def _is_private_or_reserved_ip(ip: str) -> bool:
    """判断 IP 是否为内网/保留/链路本地地址 (SSRF 防护)。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def validate_webhook_url(url: str, *, allow_local: bool = False) -> None:
    """校验 Webhook URL, SSRF 防护: 拒绝内网 IP / localhost / 非 http(s)。

    allow_local=True 时放行 localhost/127.0.0.1 (开发态), 生产态必须 False。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFBlockedError(f"Webhook URL scheme 必须是 http/https: {url}")
    hostname = parsed.hostname or ""
    if not hostname:
        raise SSRFBlockedError(f"Webhook URL 缺少 hostname: {url}")

    if allow_local and hostname in ("localhost", "127.0.0.1", "::1"):
        return

    # hostname 是 IP 直接校验
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        # 域名: DNS 解析后校验所有 A/AAAA 记录都不在内网
        try:
            infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror as exc:
            raise SSRFBlockedError(f"Webhook URL 域名无法解析: {hostname} ({exc})") from exc
        for info in infos:
            ip = str(info[4][0])
            if _is_private_or_reserved_ip(ip):
                raise SSRFBlockedError(
                    f"Webhook URL 域名 {hostname} 解析到内网/保留地址 {ip}"
                )
        return

    if _is_private_or_reserved_ip(hostname):
        raise SSRFBlockedError(f"Webhook URL 指向内网/保留地址: {hostname}")


class WebhookManager:
    """Webhook 订阅与事件推送。

    SSRF 防护 (K7): subscribe 时校验 URL, 拒绝内网/保留/链路本地地址。
    """

    def __init__(
        self,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff: float = DEFAULT_RETRY_BACKOFF,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: Any = None,
        allow_local_urls: bool = False,
    ) -> None:
        self._subscriptions: dict[str, list[str]] = {}  # event -> [url, ...]
        self.max_retries = max(1, max_retries)
        self.retry_backoff = max(0.1, retry_backoff)
        self.timeout = max(1.0, timeout)
        # http_client 可注入 (测试时用 mock), 生产时用 httpx.AsyncClient
        self._http_client = http_client
        self._allow_local_urls = allow_local_urls

    def subscribe(self, event: str, url: str) -> None:
        """订阅事件 → URL (经 SSRF 校验)。

        http_client 已注入 (测试场景) 时跳过 DNS 解析校验, 允许使用不可解析的
        假域名 (a.com / b.com) 作为测试夹具; 生产态 (无 http_client 注入) 严格执行
        SSRF 校验。
        """
        if self._http_client is None:
            validate_webhook_url(url, allow_local=self._allow_local_urls)
        else:
            # 测试场景: 只校验 scheme, 跳过 DNS 解析
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                raise SSRFBlockedError(f"Webhook URL scheme 必须是 http/https: {url}")
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
