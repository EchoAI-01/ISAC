"""EmbeddingManager: 嵌入模型管理 (ARCHITECTURE.md 3.6)。

支持本地模型 (fastembed/sentence-transformers) 和 OpenAI 兼容 API。
带降级: 模型不可用时自动降级到纯稀疏搜索 (is_degraded)。
"""

from __future__ import annotations

from typing import Any


class EmbeddingManager:
    """嵌入模型管理器。

    TODO(Day 19.5-20.5):
    - fastembed (本地) + OpenAI 兼容 API 双后端
    - 降级机制 (模型不可用时 is_degraded=True，检索降级为纯稀疏)
    - 嵌入指纹 (向量一致性检查，模型/维度变更时告警)
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化。"""
        raise NotImplementedError("TODO(Day 19.5): 实现批量向量化")

    async def embed_query(self, query: str) -> list[float]:
        """查询向量化。"""
        raise NotImplementedError("TODO(Day 19.5): 实现查询向量化")

    def get_fingerprint(self) -> dict:
        """返回模型指纹 (provider/model/dimension)，用于向量一致性检查。"""
        raise NotImplementedError("TODO(Day 19.5): 实现模型指纹")

    def is_degraded(self) -> bool:
        """是否处于降级状态 (模型不可用)。"""
        return False
