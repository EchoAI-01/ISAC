"""OpenAI 兼容视频生成 Provider 骨架 (O5, SPECIFICATION.md 2.4)。

[框架已搭建 / scaffolding] 实现 VideoGenerationProvider 契约的落点, 仿 image_gen 结构;
真实 HTTP 调用留待 O5 实现节点。视频生成 API (Sora/Runway/Kling 等) 多为受限预览,
**端点开工前需向用户二次确认**, 故 generate 暂抛 NotImplementedError, 不接入 ModelRouter。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from isac.provider.base import VideoGenerationProvider
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.artifacts.models import ArtifactRef
    from isac.artifacts.store import ArtifactStore

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 300.0  # 视频生成通常远慢于图片


class OpenAICompatVideoGenProvider(VideoGenerationProvider):
    """OpenAI 兼容视频生成 Provider 骨架。

    结构对齐 OpenAICompatImageGenProvider: 用户配置 api_base + api_key + model,
    生成结果写入 ArtifactStore 返回 ArtifactRef。骨架阶段不发起真实调用。
    """

    def __init__(
        self,
        api_base: str = "",
        api_key: str = "",
        model: str = "",
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self.api_base = api_base
        self.api_key = api_key
        self.model = model
        self._artifact_store = artifact_store

    async def generate(self, prompt: str, **kwargs: Any) -> ArtifactRef:
        """按提示词生成视频, 返回制品引用。

        TODO(O5): 对齐 image_gen 实现 —— POST 生成端点 → 轮询/等待 → 结果写 ArtifactStore
        → 返回 ArtifactRef; 错误分类复用 OpenAICompatProvider。端点确定前保持未实现。
        """
        _ = (prompt, kwargs)
        raise NotImplementedError("视频生成 Provider (O5) 尚未实现: 端点开工前需二次确认")
