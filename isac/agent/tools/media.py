"""J2 语义媒体工具 (SPECIFICATION.md 2.4)。

Agent 以语义能力 (generate_image / transcribe_audio / synthesize_speech /
understand_image / understand_video / generate_video) 调用多模态模型, 不感知
具体 Provider/模型名。工具执行链路:

    ModelRouter.select(operation, modalities_in/out)
        → ProviderManager.multimodal_provider(provider_id, model_id)
        → Provider 调用 (image_gen/stt/tts/vision_chat)
        → ArtifactStore.put (生成结果落盘) / TranscriptionResult (转写文本)
        → ToolResult (返回 artifact_id 引用或文本, 不直接返回二进制)

router 或 provider 未配置时返回友好错误, 绝不抛 NotImplementedError 给 LLM。
generate_video / understand_video 真实 API 接入留 J3+ (用户二次确认 Sora/Runway
等端点后), 当前仍返回 _NOT_WIRED 错误。

默认权限策略: deny (见 ToolPermission.DEFAULT_POLICY), 需 Agent 显式授权。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from isac.agent.tools.base import Tool, ToolContext
from isac.artifacts.models import MediaInput
from isac.core.exceptions import LLMError
from isac.core.types import ToolResult

if TYPE_CHECKING:
    from isac.artifacts.models import ArtifactRef
    from isac.artifacts.store import ArtifactStore
    from isac.provider.router import ModelRouter

_NOT_WIRED = "多模态能力尚未接入 (J2 实现节点补齐)。"
_NO_ROUTER = "未配置多模态模型路由, 无法使用该能力。"
_NO_PROVIDER = "模型未注册, 无法使用该能力。"
_NO_SELECTION = "无可用模型满足要求, 请检查配置或更换能力。"


class _MediaToolBase(Tool):
    """媒体工具公共骨架: 走 router → provider → artifact_store 真实链路。"""

    _operation = ""
    _modalities_in: set[str] = set()
    _modalities_out: set[str] = set()

    async def execute(self, context: ToolContext) -> ToolResult:
        router: ModelRouter | None = context.services.get("model_router")
        pm: Any = context.services.get("provider_manager")
        artifact_store: ArtifactStore | None = context.services.get("artifact_store")
        if router is None or pm is None:
            return ToolResult(content=_NO_ROUTER, is_error=True)
        selection = router.select(
            operation=self._operation,
            modalities_in=self._modalities_in or None,
            modalities_out=self._modalities_out or None,
        )
        if selection is None:
            return ToolResult(content=_NO_SELECTION, is_error=True)
        descriptor = selection.descriptor
        provider = pm.multimodal_provider(descriptor.provider_id, descriptor.model_id)
        if provider is None:
            return ToolResult(content=_NO_PROVIDER, is_error=True)
        try:
            return await self._call_provider(provider, context, artifact_store)
        except LLMError as exc:
            return ToolResult(content=f"模型调用失败: {exc.message}", is_error=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(content=f"工具执行异常: {exc}", is_error=True)

    async def _call_provider(
        self,
        provider: Any,
        context: ToolContext,
        artifact_store: ArtifactStore | None,
    ) -> ToolResult:
        """子类实现: 调 Provider 方法, 返回 ToolResult。"""
        return ToolResult(content=_NOT_WIRED, is_error=True)


def _format_artifact_refs(refs: list[ArtifactRef]) -> str:
    """把 ArtifactRef 列表格式化为 LLM 可读的引用文本。"""
    if not refs:
        return "未生成任何制品"
    parts = []
    for ref in refs:
        parts.append(f"artifact:{ref.artifact_id[:12]} (kind={ref.kind}, size={ref.size_bytes})")
    return "已生成制品: " + "; ".join(parts)


class GenerateImageTool(_MediaToolBase):
    _operation = "image_gen"
    _modalities_in = {"text"}
    _modalities_out = {"image"}

    @property
    def name(self) -> str:
        return "generate_image"

    @property
    def description(self) -> str:
        return "根据文字描述生成图片"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "图片内容描述"},
                "n": {"type": "integer", "description": "生成图片数 (1-10)", "default": 1},
            },
            "required": ["prompt"],
        }

    async def _call_provider(
        self, provider: Any, context: ToolContext, artifact_store: Any
    ) -> ToolResult:
        prompt = str(context.args.get("prompt", ""))
        n = int(context.args.get("n", 1) or 1)
        refs = await provider.generate(prompt, n=n)
        return ToolResult(content=_format_artifact_refs(refs), is_error=False)


class GenerateVideoTool(_MediaToolBase):
    """视频生成工具; J2 范围内不接真实 API (Sora/Runway/Kling 等需用户二次确认)。"""

    _operation = "video_gen"
    _modalities_in = {"text"}
    _modalities_out = {"video"}

    @property
    def name(self) -> str:
        return "generate_video"

    @property
    def description(self) -> str:
        return "根据文字描述生成视频"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"prompt": {"type": "string", "description": "视频内容描述"}},
            "required": ["prompt"],
        }


class TranscribeAudioTool(_MediaToolBase):
    _operation = "stt"
    _modalities_in = {"audio"}
    _modalities_out = {"text"}

    @property
    def name(self) -> str:
        return "transcribe_audio"

    @property
    def description(self) -> str:
        return "把语音转成文字"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "media_uri": {
                    "type": "string",
                    "description": "音频的受控引用 (本地绝对路径)",
                    "pattern": r"^/.*",
                },
            },
            "required": ["media_uri"],
        }

    async def _call_provider(
        self, provider: Any, context: ToolContext, artifact_store: Any
    ) -> ToolResult:
        media_uri = str(context.args.get("media_uri", ""))
        mime_type = str(context.args.get("mime_type", "audio/mpeg"))
        media: MediaInput = MediaInput(
            kind="audio", uri=media_uri, mime_type=mime_type, source="tool_input",
        )
        result = await provider.transcribe(media)
        return ToolResult(content=result.text, is_error=False)


class SynthesizeSpeechTool(_MediaToolBase):
    _operation = "tts"
    _modalities_in = {"text"}
    _modalities_out = {"audio"}

    @property
    def name(self) -> str:
        return "synthesize_speech"

    @property
    def description(self) -> str:
        return "把文字合成为语音"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要合成的文本"},
                "voice": {
                    "type": "string",
                    "description": "音色 (alloy/echo/fable/onyx/nova/shimmer)",
                    "default": "alloy",
                },
            },
            "required": ["text"],
        }

    async def _call_provider(
        self, provider: Any, context: ToolContext, artifact_store: Any
    ) -> ToolResult:
        text = str(context.args.get("text", ""))
        voice = str(context.args.get("voice", "alloy"))
        ref = await provider.synthesize(text, voice=voice)
        return ToolResult(content=_format_artifact_refs([ref]), is_error=False)


class UnderstandVideoTool(_MediaToolBase):
    """视频理解工具; J2 范围内不接真实 API (Sora/Runway 等需用户二次确认)。"""

    _operation = "video_understand"
    _modalities_in = {"video", "text"}
    _modalities_out = {"text"}

    @property
    def name(self) -> str:
        return "understand_video"

    @property
    def description(self) -> str:
        return "理解视频内容并作答"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "media_uri": {
                    "type": "string",
                    "description": "视频的受控引用 (本地绝对路径)",
                    "pattern": r"^/.*",
                },
                "prompt": {"type": "string", "description": "针对视频的问题"},
            },
            "required": ["media_uri", "prompt"],
        }


class VisionUnderstandTool(_MediaToolBase):
    """视觉理解工具: 把图片作为 image_url content 发给多模态 LLM (gpt-4o 等)。

    与 UnderstandVideoTool 区别: 这个工具处理静态图片, 调 LLMProvider.vision_chat;
    后者处理视频流, 调 VideoUnderstandingProvider.understand (J3+ 接入)。
    """

    _operation = "vision"
    _modalities_in = {"image", "text"}
    _modalities_out = {"text"}

    @property
    def name(self) -> str:
        return "understand_image"

    @property
    def description(self) -> str:
        return "理解图片内容并作答"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "media_uri": {
                    "type": "string",
                    "description": "图片的受控引用 (本地绝对路径)",
                    "pattern": r"^/.*",
                },
                "prompt": {"type": "string", "description": "针对图片的问题"},
            },
            "required": ["media_uri", "prompt"],
        }

    async def _call_provider(
        self, provider: Any, context: ToolContext, artifact_store: Any
    ) -> ToolResult:
        media_uri = str(context.args.get("media_uri", ""))
        prompt = str(context.args.get("prompt", ""))
        mime_type = str(context.args.get("mime_type", "image/png"))
        media: MediaInput = MediaInput(
            kind="image", uri=media_uri, mime_type=mime_type, source="tool_input",
        )
        response = await provider.vision_chat(media, prompt)
        return ToolResult(content=response.content, is_error=False)
