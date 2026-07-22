"""VectorStore: sqlite-vec 向量存储 (ADR-003 嵌入式方案)。

vectors 通过 id 关联 MetadataStore，按 agent_id 过滤在查询层完成。
预留 FAISS 切换接口 (DEVELOPMENT_PLAN.md 风险表)。
"""

from __future__ import annotations


class VectorStore:
    """向量存储。

    [桩] 维度由 EmbeddingManager.get_fingerprint() 决定 (向量一致性检查);
    待 sqlite-vec 连接 + vec0 虚拟表 + upsert/search 落地。
    """

    def __init__(self, db_path: str, dimension: int = 1024):
        self.db_path = db_path
        self.dimension = dimension

    async def init_schema(self) -> None:
        """MVP 暂不创建真实向量表。"""
        return None

    async def upsert(self, memory_id: str, embedding: list[float]) -> None:
        """MVP 暂不写入向量。"""
        del memory_id, embedding
        return None

    async def search(self, query_embedding: list[float], top_k: int = 10) -> list[tuple[str, float]]:
        """向量相似度搜索；MVP 默认返回空结果。"""
        del query_embedding, top_k
        return []

    async def delete(self, memory_id: str) -> None:
        """MVP 暂不删除向量。"""
        del memory_id
        return None
