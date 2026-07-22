"""EmbeddingManager: 嵌入模型管理 (ARCHITECTURE.md 3.6)。

支持本地模型 (fastembed/sentence-transformers) 和 OpenAI 兼容 API。
带降级: 模型不可用时自动降级到纯稀疏搜索 (is_degraded)。
"""

from __future__ import annotations

from typing import Any


class EmbeddingManager:
    """嵌入模型管理器。

    [已完成] 降级机制 (is_degraded 桩恒降级为纯稀疏检索) + 嵌入指纹 (get_fingerprint 返回
    provider/model/dimension/degraded);
    待落地: fastembed (本地) + OpenAI 兼容 API 双后端真实向量化。
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化; 桩实现恒返回空向量 (触发降级)。"""
        del texts
        return []

    async def embed_query(self, query: str) -> list[float]:
        """查询向量化; 桩实现恒返回空向量。"""
        del query
        return []

    def get_fingerprint(self) -> dict:
        """返回模型指纹。"""
        return {
            "provider": self.config.get("provider", "none"),
            "model": self.config.get("model", "none"),
            "dimension": int(self.config.get("dimension", 0) or 0),
            "degraded": self.is_degraded(),
        }

    def is_degraded(self) -> bool:
        """是否处于降级状态。"""
        return True
