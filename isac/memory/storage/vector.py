"""VectorStore: sqlite-vec 向量存储 (ADR-003 嵌入式方案)。

vectors 通过 id 关联 MetadataStore，按 agent_id 过滤在查询层完成。
预留 FAISS 切换接口 (DEVELOPMENT_PLAN.md 风险表)。
"""

from __future__ import annotations


class VectorStore:
    """向量存储。

    TODO(Day 19 上午): sqlite-vec 连接 + vec0 虚拟表 + upsert/search。
    维度由 EmbeddingManager.get_fingerprint() 决定 (向量一致性检查)。
    """

    def __init__(self, db_path: str, dimension: int = 1024):
        self.db_path = db_path
        self.dimension = dimension

    async def init_schema(self) -> None:
        raise NotImplementedError("TODO(Day 19): 创建 vec0 虚拟表")

    async def upsert(self, memory_id: str, embedding: list[float]) -> None:
        raise NotImplementedError("TODO(Day 19): 向量写入")

    async def search(self, query_embedding: list[float], top_k: int = 10) -> list[tuple[str, float]]:
        """向量相似度搜索，返回 (memory_id, distance) 列表。"""
        raise NotImplementedError("TODO(Day 19): 向量搜索")

    async def delete(self, memory_id: str) -> None:
        raise NotImplementedError("TODO(Day 19): 向量删除")
