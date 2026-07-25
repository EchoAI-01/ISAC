"""OpenAI 兼容 STT / TTS Provider (J2, SPECIFICATION.md 2.4)。

真实 HTTP 调用实现, 支持任意 OpenAI 兼容音频 API:
- OpenAICompatSTTProvider.transcribe: POST /audio/transcriptions (multipart/form-data)
  上传音频文件, 返回 TranscriptionResult (text/language/duration)
- OpenAICompatTTSProvider.synthesize: POST /audio/speech (JSON 请求体), 返回
  音频 bytes 写入 ArtifactStore 返回 ArtifactRef

用户配置 api_base + api_key + model 即可接入 Whisper / OpenAI Audio API
/ 阿里通义 / 自托管等任意 OpenAI 兼容音频端点。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from isac.artifacts.models import ArtifactRef, MediaInput, TranscriptionResult
from isac.core.exceptions import LLMError
from isac.provider.base import SpeechToTextProvider, TextToSpeechProvider
from isac.provider.llm.openai_compat import OpenAICompatProvider
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.artifacts.store import ArtifactStore

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 60.0


class OpenAICompatSTTProvider(SpeechToTextProvider):
    """OpenAI 兼容语音转写 Provider (Whisper / 兼容 /audio/transcriptions)。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.extra = kwargs
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover
                raise LLMError("httpx 未安装, STT Provider 不可用") from exc
            # STT 是 multipart 上传, 不要设 Content-Type (httpx 自己生成 boundary)
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
        return self._client

    async def transcribe(
        self,
        media: MediaInput,
        *,
        language: str = "auto",
        **kwargs: Any,
    ) -> TranscriptionResult:
        """读 media.uri 的音频文件 → multipart 上传 → TranscriptionResult。

        失败请求 (429/5xx/4xx) 抛 LLMError/RateLimitError, 不返回空结果。
        """
        audio_path = Path(media.uri)
        if not audio_path.is_absolute():
            raise LLMError(
                f"STT 输入 uri 必须是绝对路径 (MediaNormalizer 已校验): {media.uri}",
                retriable=False,
            )
        try:
            audio_bytes = await asyncio.to_thread(audio_path.read_bytes)
        except FileNotFoundError as exc:
            raise LLMError(
                f"STT 输入文件不存在: {media.uri}",
                retriable=False,
            ) from exc
        except OSError as exc:
            raise LLMError(
                f"STT 输入文件读取失败: {exc}",
                retriable=False,
            ) from exc

        files = {"file": (audio_path.name, audio_bytes, media.mime_type or "audio/mpeg")}
        data: dict[str, Any] = {"model": self.model}
        if language and language != "auto":
            data["language"] = language
        data.update(kwargs)

        client = self._get_client()
        try:
            response = await client.post(
                "/audio/transcriptions", files=files, data=data
            )
        except TimeoutError as exc:
            raise LLMError(f"STT 请求超时: {exc}", retriable=True) from exc
        except Exception as exc:
            raise OpenAICompatProvider._wrap_network_error(exc) from exc
        if response.status_code >= 400:
            raise OpenAICompatProvider._map_http_error(
                response.status_code, response.content
            )
        try:
            data_resp = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMError(
                f"STT 响应 JSON 解析失败: {exc}",
                retriable=False,
                context={"body": response.text[:500]},
            ) from exc
        return TranscriptionResult(
            text=str(data_resp.get("text", "") or ""),
            language=str(data_resp.get("language", "") or ""),
            duration_seconds=float(data_resp.get("duration", 0.0) or 0.0),
            segments=list(data_resp.get("segments") or []),
            metadata={"model": self.model, "provider": "openai_compat"},
        )

    def get_model_name(self) -> str:
        return self.model

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class OpenAICompatTTSProvider(TextToSpeechProvider):
    """OpenAI 兼容语音合成 Provider (OpenAI Audio / 兼容 /audio/speech)。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        artifact_store: ArtifactStore,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.artifact_store = artifact_store
        self.timeout = timeout
        self.extra = kwargs
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover
                raise LLMError("httpx 未安装, TTS Provider 不可用") from exc
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    async def synthesize(
        self,
        text: str,
        *,
        voice: str = "alloy",
        response_format: str = "mp3",
        **kwargs: Any,
    ) -> ArtifactRef:
        """按提示词合成语音, 写入 ArtifactStore 返回 ArtifactRef。

        Args:
            text: 待合成文本
            voice: 音色 (alloy/echo/fable/onyx/nova/shimmer, OpenAI 标准)
            response_format: 音频格式 (mp3/aac/flac/wav/opus)
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "input": text,
            "voice": voice,
            "response_format": response_format,
        }
        payload.update(kwargs)
        client = self._get_client()
        try:
            response = await client.post("/audio/speech", json=payload)
        except TimeoutError as exc:
            raise LLMError(f"TTS 请求超时: {exc}", retriable=True) from exc
        except Exception as exc:
            raise OpenAICompatProvider._wrap_network_error(exc) from exc
        if response.status_code >= 400:
            raise OpenAICompatProvider._map_http_error(
                response.status_code, response.content
            )
        audio_bytes = response.content
        if not audio_bytes:
            raise LLMError("TTS 响应内容为空", retriable=False)
        mime = self._format_to_mime(response_format)
        ref = await self.artifact_store.put(
            audio_bytes,
            kind="audio",
            mime_type=mime,
            metadata={
                "text": text,
                "voice": voice,
                "model": self.model,
                "provider": "openai_compat",
            },
        )
        return ref

    @staticmethod
    def _format_to_mime(fmt: str) -> str:
        return {
            "mp3": "audio/mpeg",
            "aac": "audio/aac",
            "flac": "audio/flac",
            "wav": "audio/wav",
            "opus": "audio/opus",
        }.get(fmt, "audio/mpeg")

    def get_model_name(self) -> str:
        return self.model

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
