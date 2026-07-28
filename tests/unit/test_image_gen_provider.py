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
    """url 响应格式: 用字面量公网 IP 而不是域名, 避免测试触发真实 DNS 解析
    (SSRF 校验对域名会做 socket.getaddrinfo, 对 IP 字面量走纯本地判断)。"""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/images/generations" in url:
            return httpx.Response(200, content=json.dumps({
                "created": 1234567890,
                "data": [{"url": "https://93.184.216.34/image-0.png"}],
            }).encode("utf-8"))
        # 图片下载请求
        return httpx.Response(200, content=b"\x89PNG\r\n\x1a\ndownloaded image bytes")

    provider = _make_provider(handler, artifact_store=artifact_store)
    refs = await provider.generate(prompt="a dog", n=1)
    assert len(refs) == 1
    got = await artifact_store.get(refs[0].artifact_id)
    assert got == b"\x89PNG\r\n\x1a\ndownloaded image bytes"
    await provider.aclose()


@pytest.mark.asyncio
async def test_generate_url_pointing_to_cloud_metadata_is_blocked(
    artifact_store: ArtifactStore,
) -> None:
    """安全修复: 图片生成 API 返回的 url 必须经 SSRF 校验; 169.254.169.254 是
    常见云平台元数据接口地址, 是 SSRF 攻击的经典目标。"""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/images/generations" in url:
            return httpx.Response(200, content=json.dumps({
                "created": 1234567890,
                "data": [{"url": "http://169.254.169.254/latest/meta-data/"}],
            }).encode("utf-8"))
        # 不应该真的发出这个下载请求
        return httpx.Response(200, content=b"leaked metadata")

    provider = _make_provider(handler, artifact_store=artifact_store)
    with pytest.raises(LLMError) as exc_info:
        await provider.generate(prompt="a dog", n=1)
    assert exc_info.value.retriable is False
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
async def test_generate_timeout_uses_timeout_error_mapping(
    artifact_store: ArtifactStore,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout")

    provider = _make_provider(handler, artifact_store=artifact_store)
    with pytest.raises(LLMError) as exc:
        await provider.generate("cat")
    assert exc.value.retriable is True
    assert "超时" in str(exc.value)
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
