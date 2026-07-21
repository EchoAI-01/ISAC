"""Reranker: 重排序管理 (ARCHITECTURE.md 3.6)。

支持本地模型 (bge-reranker) 和 API (Cohere/Jina)。不可用时跳过重排序。
"""

from __future__ import annotations

from typing import Any

from isac.core.types import MemoryHit


class Reranker:
    """重排序管理器。

    TODO(Day 22): bge-reranker (本地) + Cohere/Jina (API) 后端。
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config

    async def rerank(self, query: str, candidates: list[MemoryHit]) -> list[MemoryHit]:
        """对候选结果重排序。"""
        raise NotImplementedError("TODO(Day 22): 实现重排序")

    def is_available(self) -> bool:
        """重排序模型是否可用。"""
        return False
