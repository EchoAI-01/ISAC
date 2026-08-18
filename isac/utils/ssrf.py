"""出站 URL 的 SSRF (Server-Side Request Forgery) 防护。

从 isac.control.webhooks 提取到 utils 层, 使 provider/ 等更底层模块也能复用
(DEVELOP.md 导入顺序: control 依赖 provider, provider 不能反向依赖 control)。
任何代码在服务端主动请求"调用方/远程 API 提供的 URL"之前都应该先调
``validate_webhook_url`` (拒绝内网/保留/链路本地地址与非 http(s) scheme)。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse, urlsplit


class SSRFBlockedError(ValueError):
    """URL 被 SSRF 校验拒绝 (内网/链路本地/保留地址)。"""


def redact_url(url: str) -> str:
    """Fix-109: 日志/审计用的 URL 脱敏 (出站 URL 常内嵌凭据)。

    webhook/回调投递地址常把 token 放在 query (?token=...) 或 userinfo (user:pass@)。
    直接把这些 URL 写进审计/运行日志会把凭据泄进明文日志面。保留 scheme/host/path
    (运维定位信息), 掩掉 userinfo 与全部 query 值。解析失败 → 返回占位符, 绝不回显
    原值。真实投递仍用原 URL, 本函数仅供记录场景。放在 utils 层 (最底层), 供
    control/webhooks 与 control/api 两侧复用, 避免两份实现漂移。
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<invalid-url>"
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    if parts.username or parts.password:
        host = f"***@{host}"
    masked = f"{parts.scheme}://{host}{parts.path}" if parts.scheme else f"{host}{parts.path}"
    if parts.query:
        masked += "?***"
    return masked


_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


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
        or addr in _CGNAT_NETWORK  # RFC6598 CGNAT 段, ipaddress.is_private 不覆盖
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


def pin_validated_url(url: str, *, allow_local: bool = False) -> tuple[str, dict[str, str]]:
    """请求期"校验即固定": 消除校验与请求分离的 TOCTOU / DNS rebinding 窗口 (CR3-L4)。

    此前的模式是"subscribe/构造时 validate 一次, 真正 httpx 请求时独立重解析、
    不再校验"—— 低 TTL 域名可在两次解析之间重指向 169.254.169.254 等内网地址。
    本函数在发起请求前一刻调用, 返回 (request_url, extra_headers):

    - http 域名 URL: 解析并校验全部 A/AAAA 记录后, 把 URL 的 host 替换为一个已
      通过校验的 IP (优先 IPv4), 并返回 ``{"Host": 原域名}`` 头 —— 实际连接目标
      与被校验的 IP 严格一致, 重解析窗口不复存在。
    - https 域名 URL: 原样返回 (证书校验依赖原始域名做 SNI/主机名匹配, 换成 IP
      会破坏 TLS)。刚完成的重新校验已把窗口收窄到本次请求内部; 且 rebinding 到
      内网服务时对方无法出示该域名的有效证书, TLS 握手会失败, 剩余风险可接受。
    - IP 字面量 URL: 校验后原样返回 (无 DNS, 不存在 rebinding)。

    抛 SSRFBlockedError 同 validate_webhook_url。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFBlockedError(f"URL scheme 必须是 http/https: {url}")
    hostname = parsed.hostname or ""
    if not hostname:
        raise SSRFBlockedError(f"URL 缺少 hostname: {url}")

    if allow_local and hostname in ("localhost", "127.0.0.1", "::1"):
        return url, {}

    # IP 字面量: 直接校验, 无需固定
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if is_private_or_reserved_ip(hostname):
            raise SSRFBlockedError(f"URL 指向内网/保留地址: {hostname}")
        return url, {}

    resolved_ips = _resolve_and_validate_host(hostname)

    if parsed.scheme == "https":
        return url, {}

    # http: 把 host 替换为已校验 IP, Host 头保留原域名 (虚拟主机路由不受影响)
    pinned_ip = next(
        (ip for ip in resolved_ips if ":" not in ip),  # 优先 IPv4
        resolved_ips[0],
    )
    host_for_url = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
    port_part = f":{parsed.port}" if parsed.port else ""
    netloc = f"{host_for_url}{port_part}"
    pinned_url = parsed._replace(netloc=netloc).geturl()
    host_header = hostname if not parsed.port else f"{hostname}:{parsed.port}"
    return pinned_url, {"Host": host_header}


def _resolve_and_validate_host(hostname: str) -> list[str]:
    """解析域名并校验全部 A/AAAA 记录, 返回去重后的已校验 IP 列表 (CR3-L4)。"""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SSRFBlockedError(f"URL 域名无法解析: {hostname} ({exc})") from exc
    resolved_ips: list[str] = []
    for info in infos:
        ip = str(info[4][0])
        if is_private_or_reserved_ip(ip):
            raise SSRFBlockedError(f"URL 域名 {hostname} 解析到内网/保留地址 {ip}")
        if ip not in resolved_ips:
            resolved_ips.append(ip)
    if not resolved_ips:
        raise SSRFBlockedError(f"URL 域名无可用解析结果: {hostname}")
    return resolved_ips
