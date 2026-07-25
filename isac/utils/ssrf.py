"""出站 URL 的 SSRF (Server-Side Request Forgery) 防护。

从 isac.control.webhooks 提取到 utils 层, 使 provider/ 等更底层模块也能复用
(DEVELOP.md 导入顺序: control 依赖 provider, provider 不能反向依赖 control)。
任何代码在服务端主动请求"调用方/远程 API 提供的 URL"之前都应该先调
``validate_webhook_url`` (拒绝内网/保留/链路本地地址与非 http(s) scheme)。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class SSRFBlockedError(ValueError):
    """URL 被 SSRF 校验拒绝 (内网/链路本地/保留地址)。"""


def is_private_or_reserved_ip(ip: str) -> bool:
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
    """校验出站 URL, SSRF 防护: 拒绝内网 IP / localhost / 非 http(s)。

    allow_local=True 时放行 localhost/127.0.0.1 (开发态), 生产态必须 False。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFBlockedError(f"URL scheme 必须是 http/https: {url}")
    hostname = parsed.hostname or ""
    if not hostname:
        raise SSRFBlockedError(f"URL 缺少 hostname: {url}")

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
            raise SSRFBlockedError(f"URL 域名无法解析: {hostname} ({exc})") from exc
        for info in infos:
            ip = str(info[4][0])
            if is_private_or_reserved_ip(ip):
                raise SSRFBlockedError(f"URL 域名 {hostname} 解析到内网/保留地址 {ip}")
        return

    if is_private_or_reserved_ip(hostname):
        raise SSRFBlockedError(f"URL 指向内网/保留地址: {hostname}")
