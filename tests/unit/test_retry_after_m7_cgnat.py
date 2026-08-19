"""阶段3-1 M7/M6 回归: Retry-After 解析与退避 + CGNAT SSRF 封堵。

M7: 429 限流响应携带 Retry-After 头, ISAC 须解析并让退避尊重服务端建议等待 ——
此前 LLM 侧只按自己的指数退避盲目重发。
M6: safe_install 的 SSRF 防护缺 RFC6598 CGNAT 段 (100.64.0.0/10), 与 ssrf.py 口径不一致。
"""

from __future__ import annotations

import asyncio

import pytest

from isac.core.exceptions import RateLimitError
from isac.provider.llm.openai_compat import OpenAICompatProvider
from isac.provider.manager import ProviderManager
from isac.utils.retry import MAX_RETRY_AFTER_SECONDS, parse_retry_after

# ── parse_retry_after ──────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("3", 3.0),
        ("120", 60.0),  # 封顶 MAX_RETRY_AFTER_SECONDS
        ("0", None),  # 非正数
        ("-5", None),
        ("", None),
        (None, None),
        ("  7  ", 7.0),  # 去空白
        ("abc", None),  # 非数字
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),  # HTTP 日期不支持 → None 回退
    ],
)
def test_parse_retry_after(raw: str | None, expected: float | None) -> None:
    assert parse_retry_after(raw) == expected


def test_parse_retry_after_caps_at_max() -> None:
    assert parse_retry_after("999999") == MAX_RETRY_AFTER_SECONDS


# ── RateLimitError 携带 retry_after ────────────────────────────


def test_rate_limit_error_default_retry_after_none() -> None:
    assert RateLimitError("限流").retry_after is None


def test_rate_limit_error_carries_retry_after() -> None:
    assert RateLimitError("限流", retry_after=5.0).retry_after == 5.0


# ── openai_compat 429 解析 Retry-After ─────────────────────────


def test_map_http_error_429_reads_retry_after_header() -> None:
    err = OpenAICompatProvider._map_http_error(  # noqa: SLF001
        429, b"rate limited", {"retry-after": "8"}
    )
    assert isinstance(err, RateLimitError)
    assert err.retry_after == 8.0


def test_map_http_error_429_without_header_is_none() -> None:
    err = OpenAICompatProvider._map_http_error(429, b"rate limited", {})  # noqa: SLF001
    assert isinstance(err, RateLimitError)
    assert err.retry_after is None


def test_map_http_error_429_no_headers_arg_backward_compat() -> None:
    # 旧调用方不传 headers 仍可用 (默认 None)。
    err = OpenAICompatProvider._map_http_error(429, b"rate limited")  # noqa: SLF001
    assert isinstance(err, RateLimitError)
    assert err.retry_after is None


def test_map_http_error_non_429_unaffected() -> None:
    err = OpenAICompatProvider._map_http_error(500, b"oops", {"retry-after": "8"})  # noqa: SLF001
    assert not isinstance(err, RateLimitError)


# ── _retry_backoff 尊重 retry_after ────────────────────────────


@pytest.mark.asyncio
async def test_retry_backoff_honors_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    """retry_after 非空时退避至少等这么久 (取与指数退避的较大者)。"""
    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    # attempt=0, rate_limited: 指数退避基数 2^0*2=2; retry_after=10 → 应取 10。
    await ProviderManager._retry_backoff(0, rate_limited=True, retry_after=10.0)  # noqa: SLF001
    assert sleeps == [10.0]


@pytest.mark.asyncio
async def test_retry_backoff_exponential_when_retry_after_smaller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """retry_after 小于指数退避时, 仍用指数退避 (取较大者)。"""
    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    # attempt=1, rate_limited: 2^1*2=4; retry_after=1 → 取 4。
    await ProviderManager._retry_backoff(1, rate_limited=True, retry_after=1.0)  # noqa: SLF001
    assert sleeps == [4.0]


@pytest.mark.asyncio
async def test_retry_backoff_no_sleep_on_last_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    await ProviderManager._retry_backoff(2, rate_limited=True, retry_after=10.0)  # noqa: SLF001
    assert sleeps == []  # 最后一次重试后不再 sleep


# ── M6: CGNAT SSRF 封堵 ────────────────────────────────────────


def test_safe_install_rejects_cgnat_ip() -> None:
    from isac.utils.safe_install import is_safe_url

    # RFC6598 CGNAT 段 100.64.0.0/10 是运营商级内网, 必须拒。
    assert is_safe_url("http://100.64.0.1/x") is False
    assert is_safe_url("http://100.127.255.254/x") is False


def test_safe_install_cgnat_boundary_adjacent_public_ok() -> None:
    from isac.utils.safe_install import is_safe_url

    # CGNAT 段外的公网 IP 不受影响 (100.63.x 与 100.128.x 不属 100.64.0.0/10)。
    assert is_safe_url("http://100.63.0.1/x") is True
    assert is_safe_url("http://100.128.0.1/x") is True
