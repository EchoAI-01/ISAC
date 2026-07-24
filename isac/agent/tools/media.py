"""J2 语义媒体工具桩 (SPECIFICATION.md 2.4)。

Agent 以语义能力 (generate_image / transcribe_audio / synthesize_speech /
understand_video / generate_video) 调用多模态模型, 不感知具体 Provider/模型名。工具
执行时由 ModelRouter 按 operation 选择模型, 生成结果写入 ArtifactStore 返回 ArtifactRef。

骨架状态: 工具契约 (name/description/parameters) 与后端接缝就位, 默认策略为 deny
(见 ToolPermission.DEFAULT_POLICY)。真实模型选择/调用/制品落地留待 J2 实现节点;
本桩在后端未接入时返回友好错误, 绝不产生真实副作用。这些工具默认不在 assembly 注册,
待 J2 实现节点按 Agent 能力授权后接入。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult

_NOT_WIRED = "多模态能力尚未接入 (J2 实现节点补齐)。"


class _MediaToolBase(Tool):
    """媒体工具公共骨架: 校验 ModelRouter/ArtifactStore 接缝, 未接入时友好报错。"""

    _operation = ""

    async def execute(self, context: ToolContext) -> ToolResult:
        router = context.services.get("model_router")
        if router is None:
            return ToolResult(content="未配置多模态模型路由, 无法使用该能力。", is_error=True)
        # TODO(J2): router.select(operation=self._operation, ...) → Provider 调用 →
        #           ArtifactStore.put → 返回 ArtifactRef; 当前接缝就位但尚未接入真实模型。
        return ToolResult(content=_NOT_WIRED, is_error=True)


class GenerateImageTool(_MediaToolBase):
    _operation = "image_gen"

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
            "properties": {"prompt": {"type": "string", "description": "图片内容描述"}},
            "required": ["prompt"],
        }


class GenerateVideoTool(_MediaToolBase):
    _operation = "video_gen"

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
            "properties": {"media_uri": {"type": "string", "description": "音频的受控引用"}},
            "required": ["media_uri"],
        }


class SynthesizeSpeechTool(_MediaToolBase):
    _operation = "tts"

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
            "properties": {"text": {"type": "string", "description": "要合成的文本"}},
            "required": ["text"],
        }


class UnderstandVideoTool(_MediaToolBase):
    _operation = "video_understand"

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
                "media_uri": {"type": "string", "description": "视频的受控引用"},
                "prompt": {"type": "string", "description": "针对视频的问题"},
            },
            "required": ["media_uri", "prompt"],
        }
