"""J2 阶段 5d: OpenAICompatProvider.vision_chat 视觉理解测试。

gpt-4o / gpt-4-vision 等多模态 LLM 的视觉理解: 把 MediaInput 图片作为
image_url content 与 prompt 一起发给 chat/completions, 解析文本回复。

覆盖:
- vision_chat 成功 → LLMResponse.content + usage
- 请求体 messages[0].content 是 list 含 text + image_url (data URL)
- 429/5xx/4xx 错误分类
- 文件不存在 → LLMError
- aclose 释放连接池
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from isac.artifacts.models import MediaInput
from isac.core.exceptions import LLMError, RateLimitError
from isac.provider.llm.openai_compat import OpenAICompatProvider


def _make_provider(
    handler: Any,
    *,
    api_key: str = "sk-test",
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o",
) -> OpenAICompatProvider:
    provider = OpenAICompatProvider(
        api_key=api_key, base_url=base_url, model=model, timeout=5.0,
    )
    provider._client = httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        transport=httpx.MockTransport(handler),
        timeout=5.0,
    )
    return provider


def _chat_response(content: str = "a cat") -> bytes:
    body = {
        "id": "chatcmpl-x",
        "object": "chat.completion",
        "model": "gpt-4o",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    return json.dumps(body).encode("utf-8")


@pytest.mark.asyncio
async def test_vision_chat_success(tmp_path: Path) -> None:
    img_path = tmp_path / "test.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake image bytes")

    captured_request: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured_request["body"] = body
        return httpx.Response(200, content=_chat_response("a cat sitting"))

    provider = _make_provider(handler)
    media = MediaInput(kind="image", uri=str(img_path), mime_type="image/png")
    resp = await provider.vision_chat(media, prompt="What's in this image?")
    assert resp.content == "a cat sitting"
    assert resp.usage.total_tokens == 12
    # 验证请求体格式: messages[0].content 是 list, 含 text + image_url
    msg = captured_request["body"]["messages"][0]
    assert msg["role"] == "user"
    content = msg["content"]
    assert isinstance(content, list)
    types = [c.get("type") for c in content]
    assert "text" in types
    assert "image_url" in types
    # image_url.url 是 data URL (base64)
    img_url_part = next(c for c in content if c.get("type") == "image_url")
    url = img_url_part["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    # base64 部分能解码回原始字节
    b64_part = url.split(",", 1)[1]
    assert base64.b64decode(b64_part) == b"\x89PNG\r\n\x1a\nfake image bytes"
    await provider.aclose()


@pytest.mark.asyncio
async def test_vision_chat_429_raises_rate_limit(tmp_path: Path) -> None:
    img_path = tmp_path / "test.png"
    img_path.write_bytes(b"\x89PNG fake")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, content=b"rate limit")

    provider = _make_provider(handler)
    media = MediaInput(kind="image", uri=str(img_path), mime_type="image/png")
    with pytest.raises(RateLimitError):
        await provider.vision_chat(media, prompt="x")
    await provider.aclose()


@pytest.mark.asyncio
async def test_vision_chat_5xx_raises_retriable(tmp_path: Path) -> None:
    img_path = tmp_path / "test.png"
    img_path.write_bytes(b"\x89PNG fake")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"unavailable")

    provider = _make_provider(handler)
    media = MediaInput(kind="image", uri=str(img_path), mime_type="image/png")
    with pytest.raises(LLMError) as exc:
        await provider.vision_chat(media, prompt="x")
    assert exc.value.retriable is True
    await provider.aclose()


@pytest.mark.asyncio
async def test_vision_chat_4xx_raises_non_retriable(tmp_path: Path) -> None:
    img_path = tmp_path / "test.png"
    img_path.write_bytes(b"\x89PNG fake")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, content=b"bad request")

    provider = _make_provider(handler)
    media = MediaInput(kind="image", uri=str(img_path), mime_type="image/png")
    with pytest.raises(LLMError) as exc:
        await provider.vision_chat(media, prompt="x")
    assert exc.value.retriable is False
    await provider.aclose()


@pytest.mark.asyncio
async def test_vision_chat_missing_file_raises(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_chat_response("ok"))

    provider = _make_provider(handler)
    media = MediaInput(
        kind="image", uri=str(tmp_path / "missing.png"), mime_type="image/png"
    )
    with pytest.raises(LLMError):
        await provider.vision_chat(media, prompt="x")
    await provider.aclose()


@pytest.mark.asyncio
async def test_vision_chat_unsupported_kind_raises(tmp_path: Path) -> None:
    # vision_chat 只支持 image, 不支持 audio/video
    audio_path = tmp_path / "voice.mp3"
    audio_path.write_bytes(b"ID3fake")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_chat_response("ok"))

    provider = _make_provider(handler)
    media = MediaInput(kind="audio", uri=str(audio_path), mime_type="audio/mpeg")
    with pytest.raises(LLMError, match="kind"):
        await provider.vision_chat(media, prompt="x")
    await provider.aclose()


@pytest.mark.asyncio
async def test_vision_chat_default_mime_png(tmp_path: Path) -> None:
    # 不传 mime_type 时默认 image/png
    img_path = tmp_path / "test.png"
    img_path.write_bytes(b"\x89PNG fake")

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=_chat_response("ok"))

    provider = _make_provider(handler)
    media = MediaInput(kind="image", uri=str(img_path))  # mime_type 留空
    await provider.vision_chat(media, prompt="x")
    img_url = next(
        c for c in captured["body"]["messages"][0]["content"] if c.get("type") == "image_url"
    )
    assert img_url["image_url"]["url"].startswith("data:image/png;base64,")
    await provider.aclose()
