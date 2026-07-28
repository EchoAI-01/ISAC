"""J2 阶段 5b: OpenAICompat STT / TTS Provider 测试。

用 httpx.MockTransport 模拟 OpenAI /audio/transcriptions (STT, multipart)
与 /audio/speech (TTS, JSON→bytes) 响应, 覆盖:
- STT transcribe 成功 → TranscriptionResult.text + language
- TTS synthesize 成功 → ArtifactRef (audio) 存入 ArtifactStore
- 错误分类: 429 RateLimitError / 5xx retriable / 4xx non-retriable
- JSON 解析失败 / aclose 释放连接池
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from isac.artifacts.models import MediaInput
from isac.artifacts.store import ArtifactStore
from isac.core.exceptions import LLMError, RateLimitError
from isac.provider.stt_tts.openai_compat import (
    OpenAICompatSTTProvider,
    OpenAICompatTTSProvider,
)


def _make_stt_provider(
    handler: Any,
    *,
    api_key: str = "sk-test",
    base_url: str = "https://api.openai.com/v1",
    model: str = "whisper-1",
) -> OpenAICompatSTTProvider:
    provider = OpenAICompatSTTProvider(
        api_key=api_key, base_url=base_url, model=model, timeout=5.0,
    )
    provider._client = httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {api_key}"},
        transport=httpx.MockTransport(handler),
        timeout=5.0,
    )
    return provider


def _make_tts_provider(
    handler: Any,
    *,
    artifact_store: ArtifactStore,
    api_key: str = "sk-test",
    base_url: str = "https://api.openai.com/v1",
    model: str = "tts-1",
) -> OpenAICompatTTSProvider:
    provider = OpenAICompatTTSProvider(
        api_key=api_key, base_url=base_url, model=model,
        artifact_store=artifact_store, timeout=5.0,
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


# ── STT (transcribe) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_transcribe_success(tmp_path: Path) -> None:
    audio_path = tmp_path / "voice.mp3"
    audio_path.write_bytes(b"ID3fake mp3 data")

    def handler(request: httpx.Request) -> httpx.Response:
        # multipart/form-data 上传
        assert "multipart/form-data" in request.headers.get("content-type", "")
        body = {"text": "hello world", "language": "en", "duration": 5.2}
        return httpx.Response(200, content=json.dumps(body).encode("utf-8"))

    provider = _make_stt_provider(handler)
    media = MediaInput(kind="audio", uri=str(audio_path), mime_type="audio/mpeg")
    result = await provider.transcribe(media)
    assert result.text == "hello world"
    assert result.language == "en"
    assert result.duration_seconds == 5.2
    await provider.aclose()


@pytest.mark.asyncio
async def test_transcribe_429_raises_rate_limit(tmp_path: Path) -> None:
    audio_path = tmp_path / "voice.mp3"
    audio_path.write_bytes(b"ID3fake")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, content=b'{"error":"rate limit"}')

    provider = _make_stt_provider(handler)
    media = MediaInput(kind="audio", uri=str(audio_path), mime_type="audio/mpeg")
    with pytest.raises(RateLimitError):
        await provider.transcribe(media)
    await provider.aclose()


@pytest.mark.asyncio
async def test_transcribe_5xx_raises_retriable(tmp_path: Path) -> None:
    audio_path = tmp_path / "voice.mp3"
    audio_path.write_bytes(b"ID3fake")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"unavailable")

    provider = _make_stt_provider(handler)
    media = MediaInput(kind="audio", uri=str(audio_path), mime_type="audio/mpeg")
    with pytest.raises(LLMError) as exc:
        await provider.transcribe(media)
    assert exc.value.retriable is True
    await provider.aclose()


@pytest.mark.asyncio
async def test_transcribe_timeout_uses_timeout_error_mapping(tmp_path: Path) -> None:
    audio_path = tmp_path / "voice.mp3"
    audio_path.write_bytes(b"ID3fake")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout")

    provider = _make_stt_provider(handler)
    media = MediaInput(kind="audio", uri=str(audio_path), mime_type="audio/mpeg")
    with pytest.raises(LLMError) as exc:
        await provider.transcribe(media)
    assert exc.value.retriable is True
    assert "超时" in str(exc.value)
    await provider.aclose()


@pytest.mark.asyncio
async def test_transcribe_4xx_raises_non_retriable(tmp_path: Path) -> None:
    audio_path = tmp_path / "voice.mp3"
    audio_path.write_bytes(b"ID3fake")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b"unauthorized")

    provider = _make_stt_provider(handler)
    media = MediaInput(kind="audio", uri=str(audio_path), mime_type="audio/mpeg")
    with pytest.raises(LLMError) as exc:
        await provider.transcribe(media)
    assert exc.value.retriable is False
    await provider.aclose()


@pytest.mark.asyncio
async def test_transcribe_json_parse_failure_raises(tmp_path: Path) -> None:
    audio_path = tmp_path / "voice.mp3"
    audio_path.write_bytes(b"ID3fake")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    provider = _make_stt_provider(handler)
    media = MediaInput(kind="audio", uri=str(audio_path), mime_type="audio/mpeg")
    with pytest.raises(LLMError) as exc:
        await provider.transcribe(media)
    assert exc.value.retriable is False
    await provider.aclose()


@pytest.mark.asyncio
async def test_transcribe_missing_audio_file_raises(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"text":"ok"}')

    provider = _make_stt_provider(handler)
    media = MediaInput(
        kind="audio", uri=str(tmp_path / "missing.mp3"), mime_type="audio/mpeg"
    )
    with pytest.raises(LLMError):
        await provider.transcribe(media)
    await provider.aclose()


# ── TTS (synthesize) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesize_success_stores_to_artifact_store(
    tmp_path: Path,
) -> None:
    artifact_store = ArtifactStore(str(tmp_path / "artifacts"))

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "tts-1"
        assert body["input"] == "hello"
        assert body["voice"] == "alloy"
        return httpx.Response(
            200, content=b"ID3fake mp3 audio bytes", headers={"content-type": "audio/mpeg"}
        )

    provider = _make_tts_provider(handler, artifact_store=artifact_store)
    ref = await provider.synthesize(text="hello", voice="alloy")
    assert ref.kind == "audio"
    assert ref.mime_type == "audio/mpeg"
    assert ref.size_bytes > 0
    got = await artifact_store.get(ref.artifact_id)
    assert got == b"ID3fake mp3 audio bytes"
    await provider.aclose()


@pytest.mark.asyncio
async def test_synthesize_429_raises_rate_limit(tmp_path: Path) -> None:
    artifact_store = ArtifactStore(str(tmp_path / "artifacts"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, content=b"rate limit")

    provider = _make_tts_provider(handler, artifact_store=artifact_store)
    with pytest.raises(RateLimitError):
        await provider.synthesize(text="hello")
    await provider.aclose()


@pytest.mark.asyncio
async def test_synthesize_5xx_raises_retriable(tmp_path: Path) -> None:
    artifact_store = ArtifactStore(str(tmp_path / "artifacts"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"server error")

    provider = _make_tts_provider(handler, artifact_store=artifact_store)
    with pytest.raises(LLMError) as exc:
        await provider.synthesize(text="hello")
    assert exc.value.retriable is True
    await provider.aclose()


@pytest.mark.asyncio
async def test_synthesize_timeout_uses_timeout_error_mapping(tmp_path: Path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"))

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout")

    provider = _make_tts_provider(handler, artifact_store=store)
    with pytest.raises(LLMError) as exc:
        await provider.synthesize("hello")
    assert exc.value.retriable is True
    assert "超时" in str(exc.value)
    await provider.aclose()


@pytest.mark.asyncio
async def test_synthesize_4xx_raises_non_retriable(tmp_path: Path) -> None:
    artifact_store = ArtifactStore(str(tmp_path / "artifacts"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, content=b"bad request")

    provider = _make_tts_provider(handler, artifact_store=artifact_store)
    with pytest.raises(LLMError) as exc:
        await provider.synthesize(text="hello")
    assert exc.value.retriable is False
    await provider.aclose()


@pytest.mark.asyncio
async def test_synthesize_empty_audio_raises(tmp_path: Path) -> None:
    artifact_store = ArtifactStore(str(tmp_path / "artifacts"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")  # 空音频

    provider = _make_tts_provider(handler, artifact_store=artifact_store)
    with pytest.raises(LLMError):
        await provider.synthesize(text="hello")
    await provider.aclose()


@pytest.mark.asyncio
async def test_stt_aclose_releases_client(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"text":"ok"}')

    provider = _make_stt_provider(handler)
    assert provider._client is not None
    await provider.aclose()
    assert provider._client is None


@pytest.mark.asyncio
async def test_tts_aclose_releases_client(tmp_path: Path) -> None:
    artifact_store = ArtifactStore(str(tmp_path / "artifacts"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"audio bytes")

    provider = _make_tts_provider(handler, artifact_store=artifact_store)
    assert provider._client is not None
    await provider.aclose()
    assert provider._client is None
