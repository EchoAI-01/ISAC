"""Fix-76: webhook 请求体体积上限 (webhook_guard) 单元测试。"""

from __future__ import annotations

from typing import Any

import pytest

from isac.channel.webhook_guard import read_body_limited


class _StreamReq:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def stream(self) -> Any:
        for c in self._chunks:
            yield c


class _BodyReq:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def body(self) -> bytes:
        return self._data


@pytest.mark.asyncio
async def test_stream_within_limit_returns_full_body() -> None:
    req = _StreamReq([b"hello ", b"world"])
    assert await read_body_limited(req, 100) == b"hello world"


@pytest.mark.asyncio
async def test_stream_over_limit_returns_none() -> None:
    req = _StreamReq([b"x" * 600, b"y" * 600])
    assert await read_body_limited(req, 1000) is None


@pytest.mark.asyncio
async def test_body_fallback_within_limit() -> None:
    assert await read_body_limited(_BodyReq(b"abc"), 10) == b"abc"


@pytest.mark.asyncio
async def test_body_fallback_over_limit_returns_none() -> None:
    assert await read_body_limited(_BodyReq(b"x" * 100), 10) is None


@pytest.mark.asyncio
async def test_empty_body_ok() -> None:
    assert await read_body_limited(_StreamReq([]), 10) == b""
