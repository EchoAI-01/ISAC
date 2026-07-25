"""model_capabilities 注入器 (J2, SPECIFICATION.md 2.4)。

Agent 只感知其被授权且当前健康的语义能力 (transcribe_audio / synthesize_speech /
generate_image / understand_video / generate_video)。模型与 Provider 名称默认不进入
Prompt, 避免 Agent 绑定具体厂商; 工具执行时再由 ModelRouter 选择模型。

骨架状态: 按授权能力集合渲染语义说明; 健康过滤依赖 ModelCatalog/Router, 留待实现节点。
"""

from __future__ import annotations

from isac.core.injector import PromptInjector
from isac.core.types import InjectionContext

# 语义能力 → 面向 Agent 的自然语言说明 (不暴露 Provider / 模型名)。
_CAPABILITY_HINTS = {
    "transcribe_audio": "把语音转成文字",
    "synthesize_speech": "把文字合成为语音",
    "generate_image": "根据描述生成图片",
    "understand_video": "理解视频内容",
    "generate_video": "根据描述生成视频",
}


class ModelCapabilitiesInjector(PromptInjector):
    """向 System Prompt 注入 Agent 被授权的多模态能力说明。"""

    def __init__(self, allowed_capabilities: list[str] | None = None) -> None:
        # 仅保留已知的语义能力, 未知能力忽略 (授权矩阵解析在实现节点完善)。
        self._capabilities = [c for c in (allowed_capabilities or []) if c in _CAPABILITY_HINTS]

    @property
    def key(self) -> str:
        return "model_capabilities"

    @property
    def priority(self) -> int:
        return 65

    async def build(self, context: InjectionContext) -> str:
        if not self._capabilities:
            return ""
        lines = ["你还具备以下能力, 需要时可以使用:"]
        lines.extend(f"- {_CAPABILITY_HINTS[c]}" for c in self._capabilities)
        return "\n".join(lines)
