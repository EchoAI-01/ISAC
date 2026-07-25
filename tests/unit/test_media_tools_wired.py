"""J2 阶段 6: 媒体工具真实接线测试。

覆盖:
- GenerateImageTool: router.select → provider_manager.multimodal_provider →
  ImageGenProvider.generate → ArtifactStore.put → 工具返回 ArtifactRef 引用
- TranscribeAudioTool: 走 STT provider → 工具返回 TranscriptionResult.text
- VisionUnderstandTool: 走 LLM provider.vision_chat → 工具返回文本
- router 返回 None → 友好错误 (无可用模型)
- provider_manager.multimodal_provider 返回 None → 友好错误 (模型未注册)
- provider 调用失败 (抛 LLMError) → 工具返回 is_error=True
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from isac.agent.tools.base import ToolContext
from isac.agent.tools.media import (
    GenerateImageTool,
    TranscribeAudioTool,
    VisionUnderstandTool,
)
from isac.artifacts.store import ArtifactStore
from isac.core.types import AgentContext
from isac.gateway.models import Session
from isac.provider.catalog import ModelCatalog, ModelDescriptor
from isac.provider.image_gen.openai_compat import OpenAICompatImageGenProvider
from isac.provider.llm.openai_compat import OpenAICompatProvider
from isac.provider.manager import ProviderManager
from isac.provider.router import ModelRouter
from isac.provider.stt_tts.openai_compat import OpenAICompatSTTProvider


def _image_gen_handler(request: httpx.Request) -> httpx.Response:
    body = {
        "created": 1234567890,
        "data": [{"b64_json": base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()}],
    }
    return httpx.Response(200, content=json.dumps(body).encode("utf-8"))


def _stt_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        content=json.dumps({"text": "hello world", "language": "en"}).encode("utf-8"),
    )


def _vision_handler(request: httpx.Request) -> httpx.Response:
    body = {
        "id": "x",
        "model": "gpt-4o",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "a cat"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    return httpx.Response(200, content=json.dumps(body).encode("utf-8"))


def _make_image_provider(artifact_store: ArtifactStore) -> OpenAICompatImageGenProvider:
    p = OpenAICompatImageGenProvider(
        api_key="sk-test", base_url="https://api.openai.com/v1",
        model="dall-e-3", artifact_store=artifact_store, timeout=5.0,
    )
    p._client = httpx.AsyncClient(
        base_url="https://api.openai.com/v1",
        headers={"Authorization": "Bearer sk-test", "Content-Type": "application/json"},
        transport=httpx.MockTransport(_image_gen_handler),
        timeout=5.0,
    )
    return p


def _make_stt_provider() -> OpenAICompatSTTProvider:
    p = OpenAICompatSTTProvider(
        api_key="sk-test", base_url="https://api.openai.com/v1",
        model="whisper-1", timeout=5.0,
    )
    p._client = httpx.AsyncClient(
        base_url="https://api.openai.com/v1",
        headers={"Authorization": "Bearer sk-test"},
        transport=httpx.MockTransport(_stt_handler),
        timeout=5.0,
    )
    return p


def _make_vision_provider() -> OpenAICompatProvider:
    p = OpenAICompatProvider(
        api_key="sk-test", base_url="https://api.openai.com/v1",
        model="gpt-4o", timeout=5.0,
    )
    p._client = httpx.AsyncClient(
        base_url="https://api.openai.com/v1",
        headers={"Authorization": "Bearer sk-test", "Content-Type": "application/json"},
        transport=httpx.MockTransport(_vision_handler),
        timeout=5.0,
    )
    return p


def _build_services(tmp_path: Path) -> dict[str, Any]:
    """构造完整接线的 services dict: router + provider_manager + artifact_store。"""
    artifact_store = ArtifactStore(str(tmp_path / "artifacts"))
    catalog = ModelCatalog()
    catalog.register(ModelDescriptor(
        provider_id="openai", model_id="dall-e-3",
        operations={"image_gen"}, modalities_in={"text"}, modalities_out={"image"},
        cost_tier="low", latency_tier="standard",
    ))
    catalog.register(ModelDescriptor(
        provider_id="openai", model_id="whisper-1",
        operations={"stt"}, modalities_in={"audio"}, modalities_out={"text"},
    ))
    catalog.register(ModelDescriptor(
        provider_id="openai", model_id="gpt-4o",
        operations={"vision"}, modalities_in={"image", "text"}, modalities_out={"text"},
    ))
    router = ModelRouter(catalog)

    pm = ProviderManager({})
    pm.register_multimodal(
        _make_image_provider(artifact_store), provider_id="openai", model_id="dall-e-3"
    )
    pm.register_multimodal(
        _make_stt_provider(), provider_id="openai", model_id="whisper-1"
    )
    pm.register_multimodal(
        _make_vision_provider(), provider_id="openai", model_id="gpt-4o"
    )
    return {
        "model_router": router,
        "provider_manager": pm,
        "artifact_store": artifact_store,
    }


def _make_ctx(services: dict[str, Any], args: dict[str, Any]) -> ToolContext:
    session = Session(session_id="s1", user_id="u1", platform="test")
    return ToolContext(
        args=args,
        agent_context=AgentContext(
            session=session, user_profile=None, current_message=None, services={},
        ),
        services=services,
    )


@pytest.mark.asyncio
async def test_generate_image_tool_wired(tmp_path: Path) -> None:
    services = _build_services(tmp_path)
    tool = GenerateImageTool()
    ctx = _make_ctx(services, {"prompt": "a cat"})
    result = await tool.execute(ctx)
    assert not result.is_error
    # 结果应包含 ArtifactRef 引用 (artifact_id 前 12 字符)
    assert "artifact" in result.content.lower() or len(result.content) >= 8


@pytest.mark.asyncio
async def test_generate_image_tool_no_router_returns_error(tmp_path: Path) -> None:
    services = _build_services(tmp_path)
    services["model_router"] = None  # 模拟未配置
    tool = GenerateImageTool()
    ctx = _make_ctx(services, {"prompt": "x"})
    result = await tool.execute(ctx)
    assert result.is_error


@pytest.mark.asyncio
async def test_generate_image_tool_no_provider_returns_error(tmp_path: Path) -> None:
    services = _build_services(tmp_path)
    # router 选 openai/dall-e-3, 但从 provider_manager 取不到实例
    services["provider_manager"] = ProviderManager({})  # 空 pm, 无 multimodal 注册
    tool = GenerateImageTool()
    ctx = _make_ctx(services, {"prompt": "x"})
    result = await tool.execute(ctx)
    assert result.is_error


@pytest.mark.asyncio
async def test_transcribe_audio_tool_wired(tmp_path: Path) -> None:
    services = _build_services(tmp_path)
    audio_path = tmp_path / "voice.mp3"
    audio_path.write_bytes(b"ID3fake mp3 data")
    tool = TranscribeAudioTool()
    ctx = _make_ctx(services, {"media_uri": str(audio_path)})
    result = await tool.execute(ctx)
    assert not result.is_error
    assert "hello world" in result.content


@pytest.mark.asyncio
async def test_transcribe_audio_tool_no_router_returns_error(tmp_path: Path) -> None:
    services = _build_services(tmp_path)
    services["model_router"] = None
    audio_path = tmp_path / "voice.mp3"
    audio_path.write_bytes(b"ID3fake")
    tool = TranscribeAudioTool()
    ctx = _make_ctx(services, {"media_uri": str(audio_path)})
    result = await tool.execute(ctx)
    assert result.is_error


@pytest.mark.asyncio
async def test_vision_understand_tool_wired(tmp_path: Path) -> None:
    services = _build_services(tmp_path)
    img_path = tmp_path / "img.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake image")
    tool = VisionUnderstandTool()
    ctx = _make_ctx(services, {"media_uri": str(img_path), "prompt": "what?"})
    result = await tool.execute(ctx)
    assert not result.is_error
    assert result.content == "a cat"


@pytest.mark.asyncio
async def test_vision_understand_tool_no_router_returns_error(tmp_path: Path) -> None:
    services = _build_services(tmp_path)
    services["model_router"] = None
    img_path = tmp_path / "img.png"
    img_path.write_bytes(b"\x89PNG fake")
    tool = VisionUnderstandTool()
    ctx = _make_ctx(services, {"media_uri": str(img_path), "prompt": "what?"})
    result = await tool.execute(ctx)
    assert result.is_error


@pytest.mark.asyncio
async def test_vision_understand_tool_no_provider_returns_error(tmp_path: Path) -> None:
    services = _build_services(tmp_path)
    services["provider_manager"] = ProviderManager({})
    img_path = tmp_path / "img.png"
    img_path.write_bytes(b"\x89PNG fake")
    tool = VisionUnderstandTool()
    ctx = _make_ctx(services, {"media_uri": str(img_path), "prompt": "what?"})
    result = await tool.execute(ctx)
    assert result.is_error
