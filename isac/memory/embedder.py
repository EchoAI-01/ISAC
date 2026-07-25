"""EmbeddingManager: 嵌入模型管理 (ARCHITECTURE.md 3.6)。

J2 改造: 接受 EmbeddingProvider 注入 (OpenAICompatEmbeddingProvider 或任意 ABC 子类);
未注入时保持降级 (is_degraded=True, embed 返回空), 触发 MemoryRetrievalPipeline
纯稀疏检索路径, 与 D6 行为一致。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.provider.base import EmbeddingProvider


class EmbeddingManager:
    """嵌入模型管理器: 委托注入的 EmbeddingProvider, 未注入时降级。"""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        provider: EmbeddingProvider | None = None,
    ) -> None:
        self.config = config
        self._provider = provider

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化; 未注入 Provider 时返回空 (触发降级)。"""
        if self._provider is None:
            return []
        return await self._provider.embed(texts)

    async def embed_query(self, query: str) -> list[float]:
        """查询向量化; 未注入 Provider 时返回空。"""
        if self._provider is None:
            return []
        return await self._provider.embed_query(query)

    def get_fingerprint(self) -> dict:
        """返回模型指纹。"""
        return {
            "provider": self.config.get("provider", "none"),
            "model": self.config.get("model", "none"),
            "dimension": self._provider_dim(),
            "degraded": self.is_degraded(),
        }

    def _provider_dim(self) -> int:
        """从注入 Provider 取维度; 未注入或未调用过返回 0。"""
        if self._provider is None:
            return 0
        try:
            return int(self._provider.dimension())
        except Exception:  # noqa: BLE001
            return 0

    def is_degraded(self) -> bool:
        """未注入 Provider 视为降级 (纯稀疏检索)。"""
        return self._provider is None
