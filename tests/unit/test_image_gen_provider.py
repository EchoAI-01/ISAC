"""J2 阶段 5a: OpenAICompatImageGenProvider 测试。

用 httpx.MockTransport 模拟 OpenAI /images/generations 响应, 覆盖:
- b64_json 响应 → 多张图存入 ArtifactStore
- url 响应 → 下载图片后存入 ArtifactStore
- 429 → RateLimitError; 5xx → LLMError(retriable=True); 4xx → LLMError(retriable=False)
- JSON 解析失败 / 空 data → LLMError
- aclose 释放连接池
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from isac.artifacts.store import ArtifactStore
from isac.core.exceptions import LLMError, RateLimitError
from isac.provider.image_gen.openai_compat import OpenAICompatImageGenProvider


def _make_provider(
    handler: Any,
    *,
    artifact_store: ArtifactStore,
    api_key: str = "sk-test",
    base_url: str = "https://api.openai.com/v1",
    model: str = "dall-e-3",
) -> OpenAICompatImageGenProvider:
    provider = OpenAICompatImageGenProvider(
        api_key=api_key, base_url=base_url, model=model,
        artifact_store=artifact_store, timeout=5.0,
    )
    provider._client = httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        transport=httpx.MockTransport(handler),
        timeout=5.0,
    )
    return provider


def _b64_response(n: int = 1) -> bytes:
    """构造 OpenAI /images/generations b64_json 响应 (n 张图)。"""
    data = [
        {"b64_json": base64.b64encode(b"\x89PNG\r\n\x1a\nfake" + bytes([i])).decode()}
        for i in range(n)
    ]
    return json.dumps({"created": 1234567890, "data": data}).encode("utf-8")


def _url_response(n: int = 1) -> bytes:
    """构造 OpenAI /images/generations url 响应 (n 张图)。"""
    data = [{"url": f"https://cdn.openai.com/image-{i}.png"} for i in range(n)]
    return json.dumps({"created": 1234567890, "data": data}).encode("utf-8")


@pytest.fixture
def artifact_store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(str(tmp_path / "artifacts"))


@pytest.mark.asyncio
async def test_generate_b64_success_stores_to_artifact_store(
    artifact_store: ArtifactStore,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_b64_response(n=2))

    provider = _make_provider(handler, artifact_store=artifact_store)
    refs = await provider.generate(prompt="a cat", n=2)
    assert len(refs) == 2
    for ref in refs:
        assert ref.kind == "image"
        assert ref.mime_type == "image/png"
        assert ref.size_bytes > 0
        got = await artifact_store.get(ref.artifact_id)
        assert got is not None
        assert got.startswith(b"\x89PNG")
    await provider.aclose()


@pytest.mark.asyncio
async def test_generate_url_downloads_and_stores(
    artifact_store: ArtifactStore,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/images/generations" in url:
            return httpx.Response(200, content=_url_response(n=1))
        # 图片下载请求 (https://cdn.openai.com/image-0.png)
        return httpx.Response(200, content=b"\x89PNG\r\n\x1a\ndownloaded image bytes")

    provider = _make_provider(handler, artifact_store=artifact_store)
    refs = await provider.generate(prompt="a dog", n=1)
    assert len(refs) == 1
    got = await artifact_store.get(refs[0].artifact_id)
    assert got == b"\x89PNG\r\n\x1a\ndownloaded image bytes"
    await provider.aclose()


@pytest.mark.asyncio
async def test_generate_429_raises_rate_limit(
    artifact_store: ArtifactStore,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, content=b'{"error":"rate limit"}')

    provider = _make_provider(handler, artifact_store=artifact_store)
    with pytest.raises(RateLimitError):
        await provider.generate(prompt="x")
    await provider.aclose()


@pytest.mark.asyncio
async def test_generate_5xx_raises_retriable(
    artifact_store: ArtifactStore,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"server error")

    provider = _make_provider(handler, artifact_store=artifact_store)
    with pytest.raises(LLMError) as exc:
        await provider.generate(prompt="x")
    assert exc.value.retriable is True
    await provider.aclose()


@pytest.mark.asyncio
async def test_generate_4xx_raises_non_retriable(
    artifact_store: ArtifactStore,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b"unauthorized")

    provider = _make_provider(handler, artifact_store=artifact_store)
    with pytest.raises(LLMError) as exc:
        await provider.generate(prompt="x")
    assert exc.value.retriable is False
    await provider.aclose()


@pytest.mark.asyncio
async def test_generate_json_parse_failure_raises(
    artifact_store: ArtifactStore,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    provider = _make_provider(handler, artifact_store=artifact_store)
    with pytest.raises(LLMError) as exc:
        await provider.generate(prompt="x")
    assert exc.value.retriable is False
    await provider.aclose()


@pytest.mark.asyncio
async def test_generate_empty_data_raises(
    artifact_store: ArtifactStore,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"created":0,"data":[]}')

    provider = _make_provider(handler, artifact_store=artifact_store)
    with pytest.raises(LLMError):
        await provider.generate(prompt="x")
    await provider.aclose()


@pytest.mark.asyncio
async def test_aclose_releases_client(artifact_store: ArtifactStore) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_b64_response(n=1))

    provider = _make_provider(handler, artifact_store=artifact_store)
    assert provider._client is not None
    await provider.aclose()
    assert provider._client is None


@pytest.mark.asyncio
async def test_get_model_name_returns_configured(
    artifact_store: ArtifactStore,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_b64_response(n=1))

    provider = _make_provider(handler, artifact_store=artifact_store, model="dall-e-3")
    assert provider.get_model_name() == "dall-e-3"
    await provider.aclose()
