"""MemoryRetrievalPipeline: 记忆检索流水线 (ARCHITECTURE.md 3.6)。

检索流程: Query → [Embed] → Dense Search + Sparse (BM25) → [RRF Fusion]
         → [Reranker] → Top-K → Format → Inject
契约见 SPECIFICATION.md 2.4；错误处理: 检索失败返回空列表 (SPECIFICATION.md 5.1)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.core.types import MemoryHit
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.memory.embedder import EmbeddingManager
    from isac.memory.reranker import Reranker
    from isac.memory.storage.graph import GraphStore
    from isac.memory.storage.metadata import MetadataStore
    from isac.memory.storage.sparse import SparseBM25Index
    from isac.memory.storage.vector import VectorStore

logger = get_logger(__name__)


class MemoryRetrievalPipeline:
    """记忆检索流水线。每个 AgentInstance 持有一个 (绑定记忆命名空间)。"""

    def __init__(
        self,
        namespace: str,
        metadata: MetadataStore,
        vector: VectorStore,
        sparse: SparseBM25Index,
        graph: GraphStore,
        embedder: EmbeddingManager,
        reranker: Reranker | None = None,
    ):
        """
        Args:
            namespace: 记忆命名空间 (通常 = agent_id; "shared" 跨 Agent 共享)
        """
        self.namespace = namespace
        self.metadata = metadata
        self.vector = vector
        self.sparse = sparse
        self.graph = graph
        self.embedder = embedder
        self.reranker = reranker

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filters: dict | None = None,
        agent_id: str = "",
        user_id: str = "",
        group_id: str = "",
    ) -> list[MemoryHit]:
        """检索记忆 (契约见 SPECIFICATION.md 2.4)。

        TODO(Day 21): Embed → Dense + Sparse (+ Graph) → RRF Fusion → Rerank → Top-K。
        全程按 self.namespace 过滤；embedder.is_degraded() 时跳过 Dense。
        失败时返回空列表，不阻塞消息流 (SPECIFICATION.md 5.1)。
        """
        raise NotImplementedError("TODO(Day 21): 实现双路径检索 + RRF 融合 + 重排序")

    async def store_episode(
        self,
        content: str,
        session_id: str,
        user_id: str,
        agent_id: str = "",
        metadata: dict | None = None,
    ) -> str:
        """存储一条情景记忆 (写入本命名空间)。返回记忆 ID。

        TODO(Day 21): MetadataStore.store_episode + Embedding + VectorStore.upsert。
        存储失败记录日志，不阻塞消息流 (SPECIFICATION.md 5.1)。
        """
        raise NotImplementedError("TODO(Day 21): 实现记忆存储")
