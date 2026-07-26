"""SSRF 校验的规范化位置 (isac.utils.ssrf)。

从 isac.control.webhooks 提取出来, 使 provider/ 等更底层模块也能复用 (DEVELOP.md
导入顺序: control 依赖 provider, provider 不能反向依赖 control)。
isac.control.webhooks 保留原有名字重新导出, 向后兼容既有调用方。
"""

from __future__ import annotations

import pytest

from isac.utils.ssrf import SSRFBlockedError, is_private_or_reserved_ip, validate_webhook_url


def test_validate_webhook_url_rejects_loopback() -> None:
    with pytest.raises(SSRFBlockedError):
        validate_webhook_url("http://127.0.0.1/steal")


def test_validate_webhook_url_rejects_cloud_metadata_ip() -> None:
    """169.254.169.254 是常见云平台元数据接口地址, 是 SSRF 攻击的经典目标。"""
    with pytest.raises(SSRFBlockedError):
        validate_webhook_url("http://169.254.169.254/latest/meta-data/")


def test_validate_webhook_url_rejects_non_http_scheme() -> None:
    with pytest.raises(SSRFBlockedError):
        validate_webhook_url("file:///etc/passwd")


def test_validate_webhook_url_allows_public_ip() -> None:
    validate_webhook_url("https://1.1.1.1/webhook")  # 不抛异常即通过


def test_is_private_or_reserved_ip_true_for_link_local() -> None:
    assert is_private_or_reserved_ip("169.254.169.254") is True


def test_is_private_or_reserved_ip_false_for_public() -> None:
    assert is_private_or_reserved_ip("8.8.8.8") is False


def test_webhooks_module_reexports_for_backward_compat() -> None:
    """isac.control.webhooks 必须继续能导出这三个名字, 不破坏既有调用方。"""
    from isac.control.webhooks import SSRFBlockedError as ReExportedError
    from isac.control.webhooks import validate_webhook_url as reexported_validate

    assert ReExportedError is SSRFBlockedError
    assert reexported_validate is validate_webhook_url


# ── CR3-L4: 请求期"校验即固定" (pin_validated_url) ─────────────


def test_pin_validated_url_ip_literal_passthrough() -> None:
    """IP 字面量无 DNS 环节, 校验通过后原样返回。"""
    from isac.utils.ssrf import pin_validated_url

    url, headers = pin_validated_url("https://1.1.1.1/webhook")
    assert url == "https://1.1.1.1/webhook"
    assert headers == {}


def test_pin_validated_url_blocks_private_ip() -> None:
    from isac.utils.ssrf import pin_validated_url

    with pytest.raises(SSRFBlockedError):
        pin_validated_url("http://169.254.169.254/latest/meta-data/")


def test_pin_validated_url_pins_http_domain_to_validated_ip(monkeypatch) -> None:
    """http 域名 URL: host 替换为已校验 IP, Host 头保留原域名 (消除重解析窗口)。"""
    import socket

    from isac.utils.ssrf import pin_validated_url

    def fake_getaddrinfo(host, port, *args, **kwargs):
        assert host == "hooks.example.com"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    url, headers = pin_validated_url("http://hooks.example.com:8080/notify?x=1")
    assert url == "http://93.184.216.34:8080/notify?x=1"
    assert headers == {"Host": "hooks.example.com:8080"}


def test_pin_validated_url_https_domain_kept_but_revalidated(monkeypatch) -> None:
    """https 域名 URL 保留原样 (TLS 证书校验依赖域名), 但解析到内网仍拒绝。"""
    import socket

    from isac.utils.ssrf import pin_validated_url

    def public_dns(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", public_dns)
    url, headers = pin_validated_url("https://hooks.example.com/notify")
    assert url == "https://hooks.example.com/notify"
    assert headers == {}

    def rebound_dns(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", rebound_dns)
    with pytest.raises(SSRFBlockedError):
        pin_validated_url("https://hooks.example.com/notify")
