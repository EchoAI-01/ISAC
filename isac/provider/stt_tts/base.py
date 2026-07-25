"""J2 语音 Provider 桩 (填充空目录)。

STT / TTS 真实实现 (Whisper / 云端语音 API) 留待 J2 实现节点; 本桩声明能力描述符
并让方法显式 NotImplementedError, 生成结果统一走 ArtifactStore 返回 ArtifactRef。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from isac.provider.base import SpeechToTextProvider, TextToSpeechProvider
from isac.provider.catalog import ModelDescriptor

if TYPE_CHECKING:
    from isac.artifacts.models import ArtifactRef, MediaInput, TranscriptionResult


class StubSpeechToTextProvider(SpeechToTextProvider):
    """占位 STT Provider: 声明能力, 转写方法待实现节点接入真实模型。"""

    def __init__(self, model_id: str = "stub-stt") -> None:
        self._model_id = model_id

    def descriptor(self) -> ModelDescriptor:
        return ModelDescriptor(
            provider_id="stub",
            model_id=self._model_id,
            modalities_in={"audio"},
            modalities_out={"text"},
            operations={"stt"},
        )

    async def transcribe(self, media: MediaInput, **kwargs: Any) -> TranscriptionResult:
        raise NotImplementedError("StubSpeechToTextProvider.transcribe 待 J2 实现节点接入真实模型")


class StubTextToSpeechProvider(TextToSpeechProvider):
    """占位 TTS Provider: 声明能力, 合成方法待实现节点接入真实模型。"""

    def __init__(self, model_id: str = "stub-tts") -> None:
        self._model_id = model_id

    def descriptor(self) -> ModelDescriptor:
        return ModelDescriptor(
            provider_id="stub",
            model_id=self._model_id,
            modalities_in={"text"},
            modalities_out={"audio"},
            operations={"tts"},
        )

    async def synthesize(self, text: str, **kwargs: Any) -> ArtifactRef:
        raise NotImplementedError("StubTextToSpeechProvider.synthesize 待 J2 实现节点接入真实模型")
