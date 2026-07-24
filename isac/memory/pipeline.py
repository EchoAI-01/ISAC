"""MemoryRetrievalPipeline: 记忆检索流水线 (ARCHITECTURE.md 3.6)。

检索流程: Query → [Embed] → Dense Search + Sparse (BM25) → [RRF Fusion]
         → [Reranker] → Top-K → Format → Inject
契约见 SPECIFICATION.md 2.4；错误处理: 检索失败返回空列表 (SPECIFICATION.md 5.1)。
"""

from __future__ import annotations

import time
import uuid
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
    from isac.observability.metrics import MetricsCollector

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
        metrics: MetricsCollector | None = None,
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
        self._metrics = metrics

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filters: dict | None = None,
        agent_id: str = "",
        user_id: str = "",
        group_id: str = "",
    ) -> list[MemoryHit]:
        """检索记忆。

        agent 隔离由 self.namespace 保证 (agent_id 参数含义相同, 仅为调用方兼容保留);
        user_id/group_id 用于 user/group 访问控制 (CODE_REVIEW_REPORT.md #9):
        群聊场景按 group_id 过滤 (群内共享)，私聊场景按 user_id 过滤且排除群聊记忆。

        shared namespace 强制 ACL (K3, DEVELOPMENT_PLAN.md): namespace="shared" 时必须
        传 user_id 或 group_id, 否则拒绝检索 (返回空) 防止跨用户注入。
        """
        del filters, agent_id  # TODO: 结构化过滤条件 (topics/时间范围等), 当前未实现
        clean_query = str(query or "").strip()
        if not clean_query:
            return []
        if self.namespace == "shared" and not user_id and not group_id:
            logger.warning(
                "shared namespace 检索被 ACL 拒绝: 缺少 user_id/group_id",
                namespace=self.namespace,
            )
            if self._metrics is not None:
                self._metrics.counter("isac_memory_acl_rejections_total").inc()
            return []
        if self._metrics is not None:
            self._metrics.counter("isac_memory_searches_total").inc()
        start = time.monotonic()
        try:
            fts_rows = await self.metadata.search_fts(
                self.namespace,
                clean_query,
                limit=max(top_k * 2, 10),
                user_id=user_id,
                group_id=group_id,
            )
            sparse_rows = self.sparse.search(clean_query, top_k=max(top_k * 2, 10))
            sparse_ids = [memory_id for memory_id, _score in sparse_rows]
            fts_ids = {str(row.get("id", "")) for row in fts_rows}
            missing_rows = await self.metadata.get_episodes_by_ids(
                self.namespace,
                [memory_id for memory_id in sparse_ids if memory_id not in fts_ids],
                user_id=user_id,
                group_id=group_id,
            )
            hits = self._merge_results([*fts_rows, *missing_rows], sparse_rows)
            if self.reranker is not None and self.reranker.is_available():
                hits = await self.reranker.rerank(clean_query, hits)
            return hits[: max(1, int(top_k))]
        except Exception as exc:
            logger.warning("记忆检索失败，返回空结果", namespace=self.namespace, error=str(exc))
            return []
        finally:
            if self._metrics is not None:
                self._metrics.histogram("isac_memory_search_latency_seconds").observe(time.monotonic() - start)

    async def warm_up_sparse_index(self) -> int:
        """从 MetadataStore 加载全部 episodes 重建 SparseBM25Index 内存索引。

        SparseBM25Index 是纯内存数据结构, 进程重启会丢失; 启动时调用本方法从 SQLite
        episodes 表读取现有 (memory_id, content) 重建倒排索引, 让 BM25 检索在重启后
        立即可用而不必等下次写入 (K3, DEVELOPMENT_PLAN.md)。

        返回加载到索引中的文档数。
        """
        try:
            pairs = await self.metadata.iter_episodes_by_namespace(self.namespace)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Sparse 索引预热失败, BM25 检索将退化为空直到下次写入",
                namespace=self.namespace, error=str(exc),
            )
            if self._metrics is not None:
                self._metrics.counter("isac_memory_store_errors_total").inc()
            return 0
        for memory_id, content in pairs:
            self.sparse.add(memory_id, content)
        if pairs and self._metrics is not None:
            self._metrics.counter("isac_memory_warmup_docs_total").inc(len(pairs))
        logger.info("Sparse 索引预热完成", namespace=self.namespace, docs=len(pairs))
        return len(pairs)

    async def store_episode(
        self,
        content: str,
        session_id: str,
        user_id: str,
        agent_id: str = "",
        group_id: str = "",
        metadata: dict | None = None,
    ) -> str:
        """存储一条情景记忆。"""
        clean_content = str(content or "").strip()
        if not clean_content:
            return ""
        payload = dict(metadata or {})
        payload.setdefault("id", str(uuid.uuid4()))
        payload["content"] = clean_content
        payload["session_id"] = session_id
        payload["user_id"] = user_id
        payload["group_id"] = group_id
        try:
            memory_id = await self.metadata.store_episode(agent_id or self.namespace, payload)
            self.sparse.add(memory_id, clean_content)
            if not self.embedder.is_degraded():
                embeddings = await self.embedder.embed([clean_content])
                if embeddings:
                    await self.vector.upsert(memory_id, embeddings[0])
            if self._metrics is not None:
                self._metrics.counter("isac_memory_stores_total").inc()
            return memory_id
        except Exception as exc:
            logger.warning("记忆存储失败，返回空 ID", namespace=self.namespace, error=str(exc))
            if self._metrics is not None:
                self._metrics.counter("isac_memory_store_errors_total").inc()
            return ""

    @staticmethod
    def _merge_results(fts_rows: list[dict], sparse_rows: list[tuple[str, float]]) -> list[MemoryHit]:
        scores: dict[str, float] = {}
        rows_by_id: dict[str, dict] = {}
        for rank, row in enumerate(fts_rows, start=1):
            memory_id = str(row.get("id", ""))
            if not memory_id:
                continue
            rows_by_id[memory_id] = row
            scores[memory_id] = scores.get(memory_id, 0.0) + 1 / (60 + rank)
        for rank, (memory_id, sparse_score) in enumerate(sparse_rows, start=1):
            scores[memory_id] = scores.get(memory_id, 0.0) + 1 / (60 + rank) + sparse_score * 0.001
        hits = []
        for memory_id, score in sorted(scores.items(), key=lambda item: (-item[1], item[0])):
            if memory_id not in rows_by_id:
                continue
            row = rows_by_id[memory_id]
            hits.append(
                MemoryHit(
                    id=memory_id,
                    content=str(row.get("content", "")),
                    source=str(row.get("session_id", "")),
                    hit_type="episode",
                    score=score,
                    metadata={
                        "summary": row.get("summary", ""),
                        "topics": row.get("topics", []),
                        "importance": row.get("importance", 0.5),
                    },
                )
            )
        return hits


class NoOpMemoryPipeline:
    """记忆流水线空实现：用于 D5-D7 完成前让主链路能启动。

    检索恒返回空列表，存储恒返回空 ID，不抛异常、不阻塞消息流。
    待真实存储后端实现后，main.py 的 memory_factory 再替换为真实流水线。
    """

    def __init__(self, namespace: str):
        self.namespace = namespace

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filters: dict | None = None,
        agent_id: str = "",
        user_id: str = "",
        group_id: str = "",
    ) -> list[MemoryHit]:
        """空检索，永远返回空列表。"""
        logger.debug("NoOp 记忆检索", namespace=self.namespace, query=query)
        return []

    async def store_episode(
        self,
        content: str,
        session_id: str,
        user_id: str,
        agent_id: str = "",
        group_id: str = "",
        metadata: dict | None = None,
    ) -> str:
        """空存储，仅记录日志。"""
        logger.debug("NoOp 记忆存储", namespace=self.namespace, session_id=session_id)
        return ""
