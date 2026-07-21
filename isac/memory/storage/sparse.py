"""SparseBM25Index: 稀疏检索 (BM25)。

与 FTS5 互补的内存 BM25 索引；嵌入模型不可用时降级为纯稀疏搜索
(EmbeddingManager.is_degraded, ARCHITECTURE.md 3.6)。
"""

from __future__ import annotations


class SparseBM25Index:
    """BM25 稀疏索引。

    TODO(Day 19 下午): 分词 + BM25 打分 (可考虑 rank_bm25 或自实现)。
    """

    def __init__(self) -> None:
        self._docs: dict[str, str] = {}  # memory_id -> content

    def add(self, memory_id: str, content: str) -> None:
        self._docs[memory_id] = content

    def remove(self, memory_id: str) -> None:
        self._docs.pop(memory_id, None)

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """BM25 搜索，返回 (memory_id, score) 列表。"""
        raise NotImplementedError("TODO(Day 19): 实现 BM25 搜索")
