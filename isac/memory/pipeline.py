"""MemoryRetrievalPipeline: 记忆检索流水线 (ARCHITECTURE.md 3.6)。

检索流程: Query → [Embed] → Dense Search + FTS5 + Sparse (BM25) → RRF Fusion
         → [Reranker] → Top-K → Format → Inject
CR3-H3: 稠密 (向量) 召回已接入 search() —— embedder 未降级时 embed_query +
vector.search 参与 RRF 融合; 向量候选统一经 get_episodes_by_ids 过滤
(agent 命名空间 + user/group ACL + deleted=0), 与稀疏候选同一套访问控制。
S3: 图谱召回 (mentioned_in 边) 已接入 search() —— store_episode 写边 (仅
enable_graph_recall=True), _graph_search 以 user_id/group_id 为种子 (满足
ACL), 邻居候选同样经 get_episodes_by_ids 过滤。

**MemoryItem 落地边界 (S3 验收明确)**: ``MemoryItem``/``MemoryItemAdapter`` 服务于
治理 (N2 ``MemoryGovernor.export``) 与跨表适配 (N1 四类 from_*/to_*), **检索热路径
(``search()``/``_merge_results()``) 继续用轻量 ``MemoryHit``** —— 不在每次查询
上做双向包装, 避免为尚无消费者的抽象层增加每请求开销。``MemoryItemAdapter.
to_hit``/``from_hit`` 作为治理 ↔ 检索边界转换的公开手段保留, 待治理路径有真实
跨表消费者时再接入; 检索路径的 ``MemoryHit`` 直接构造即可。

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


def is_shared_namespace(namespace: str) -> bool:
    """判定是否为 shared 记忆命名空间 (2026-08-19 ACL 口径统一)。

    兼容两种形态: 裸 ``"shared"`` 与租户前缀 ``"<org>:<tenant>:shared"``
    (``TenantIsolationGuard.namespace_for`` 启用租户后加前缀)。此前 pipeline 检索
    仅用 ``== "shared"`` 字面量判断, 租户模式下失配 → 强制 ACL 被绕过, 可无锚点
    全量检索该租户 shared 空间内所有用户记忆。**所有 shared 判定必须走本函数**,
    不得再自拼字面量比较 (同构面核对清单)。
    """
    return namespace == "shared" or namespace.endswith(":shared")


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
        enable_graph_recall: bool = False,
    ):
        """
        Args:
            namespace: 记忆命名空间 (通常 = agent_id; "shared" 跨 Agent 共享)
            enable_graph_recall: S3 图谱邻居召回开关 (默认关闭; 骨架期即使开启也零产出)
        """
        self.namespace = namespace
        self.metadata = metadata
        self.vector = vector
        self.sparse = sparse
        self.graph = graph
        self.embedder = embedder
        self.reranker = reranker
        self._metrics = metrics
        self._enable_graph_recall = enable_graph_recall

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
        del agent_id  # agent_id 仅为调用方兼容保留, 检索用 self.namespace 隔离
        clean_query = str(query or "").strip()
        if not clean_query:
            return []
        if is_shared_namespace(self.namespace) and not user_id and not group_id:
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
            recall_limit = max(top_k * 2, 10)
            fts_rows = await self.metadata.search_fts(
                self.namespace,
                clean_query,
                limit=recall_limit,
                user_id=user_id,
                group_id=group_id,
                filters=filters,
            )
            sparse_rows = self.sparse.search(clean_query, top_k=recall_limit)
            # CR3-H3: 稠密召回 (embedder 降级/失败时返回空, 不影响稀疏路径)
            dense_rows = await self._dense_search(clean_query, top_k=recall_limit)
            # S3: 图谱邻居召回 (默认关闭 → 空; 启用时种子 = user_id/group_id, 邻居
            # 经 graph.neighbors 取后剥 episode: 前缀, 候选统一经 get_episodes_by_ids
            # 过滤 ACL/软删, 与稠密路同一套访问控制)
            graph_rows = await self._graph_search(
                clean_query, top_k=recall_limit, user_id=user_id, group_id=group_id
            )
            fts_ids = {str(row.get("id", "")) for row in fts_rows}
            candidate_ids: list[str] = []
            for memory_id, _score in [*sparse_rows, *dense_rows, *graph_rows]:
                if memory_id not in fts_ids and memory_id not in candidate_ids:
                    candidate_ids.append(memory_id)
            # 稀疏/稠密候选统一经 get_episodes_by_ids 补齐行数据 —— 它同时执行
            # agent 命名空间隔离 + user/group ACL + deleted=0 过滤, 向量库中
            # 不属于当前访问上下文的候选在这里被丢弃 (shared-namespace ACL 一致)。
            missing_rows = await self.metadata.get_episodes_by_ids(
                self.namespace,
                candidate_ids,
                user_id=user_id,
                group_id=group_id,
                filters=filters,
            )
            hits = self._merge_results([*fts_rows, *missing_rows], sparse_rows, dense_rows, graph_rows)
            if self.reranker is not None and self.reranker.is_available():
                hits = await self.reranker.rerank(clean_query, hits)
            return hits[: max(1, int(top_k))]
        except Exception as exc:
            logger.warning("记忆检索失败，返回空结果", namespace=self.namespace, error=str(exc))
            return []
        finally:
            if self._metrics is not None:
                self._metrics.histogram("isac_memory_search_latency_seconds").observe(time.monotonic() - start)

    async def _dense_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """稠密 (向量) 召回: embed_query → vector.search (CR3-H3)。

        embedder 降级 (未注入 Provider)、query 向量为空、或向量检索抛异常时
        返回空列表 —— 稠密路径任何故障都只降级为"纯稀疏检索", 不影响 FTS/BM25
        已召回的结果 (SPECIFICATION.md 5.1 记忆失败降级)。
        """
        if self.embedder.is_degraded():
            return []
        try:
            query_embedding = await self.embedder.embed_query(query)
            if not query_embedding:
                return []
            return await self.vector.search(query_embedding, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            logger.warning("稠密检索失败, 降级为稀疏检索", namespace=self.namespace, error=str(exc))
            return []

    async def _graph_search(
        self, query: str, top_k: int, *, user_id: str = "", group_id: str = ""
    ) -> list[tuple[str, float]]:
        """图谱邻居召回: 从调用方已知的 user_id/group_id 出发经 graph.neighbors
        扩展关联记忆 (S3)。

        种子锚定在调用上下文自己的 user_id/group_id (不自由指向任意实体, 满足
        ACL 铁律); graph.neighbors 返回 [(object, weight)], object 形如
        ``episode:<id>``; 剥前缀还原 memory_id, 按 weight 降序去重截断到 top_k;
        返回的候选在 search() 主流程里再经 get_episodes_by_ids 过滤 ACL/软删
        (与稠密路同一套安全)。

        enable_graph_recall=False 或无种子 → 返回 []; 任一步失败降级 []。
        """
        if not self._enable_graph_recall:
            return []
        if not user_id and not group_id:
            return []  # 无 ACL 锚点不查 (避免横向查到别人)
        _ = query  # 当前实现不依赖 query 文本 (种子来自调用上下文)
        try:
            rows: list[tuple[str, float]] = []
            if user_id:
                rows.extend(
                    await self.graph.neighbors(
                        self.namespace, f"user:{user_id}", relation="mentioned_in"
                    )
                )
            if group_id:
                rows.extend(
                    await self.graph.neighbors(
                        self.namespace, f"group:{group_id}", relation="mentioned_in"
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "图谱邻居查询失败, 降级为空", namespace=self.namespace, error=str(exc)
            )
            return []
        # 剥 episode: 前缀还原 memory_id, 去重取最大 weight
        deduped: dict[str, float] = {}
        for obj, weight in rows:
            if not obj.startswith("episode:"):
                continue
            mid = obj[len("episode:"):]
            if not mid:
                continue
            w = float(weight or 0.0)
            if mid in deduped:
                deduped[mid] = max(deduped[mid], w)
            else:
                deduped[mid] = w
        sorted_pairs = sorted(deduped.items(), key=lambda kv: (-kv[1], kv[0]))
        return sorted_pairs[: max(1, int(top_k))]

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
        except Exception as exc:
            logger.warning("记忆存储失败，返回空 ID", namespace=self.namespace, error=str(exc))
            if self._metrics is not None:
                self._metrics.counter("isac_memory_store_errors_total").inc()
            return ""
        # N5b 批次E 项3: episode 已持久化; 下游索引同步 best-effort, 失败不撤回 episode
        # 也不返回空 ID (此前 vector.upsert 维度错配抛错被外层 except 吞, episode 入库
        # 却返回 "" → 幽灵条目 + 调用方误判失败 + 跳过画像更新)。
        try:
            self.sparse.add(memory_id, clean_content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("BM25 索引同步失败, episode 已入库", namespace=self.namespace, error=str(exc))
        if not self.embedder.is_degraded():
            try:
                embeddings = await self.embedder.embed([clean_content])
                if embeddings:
                    await self.vector.upsert(memory_id, embeddings[0])
            except Exception as exc:  # noqa: BLE001
                logger.warning("向量索引写入失败, episode 已入库 (稀疏检索仍可用)",
                               namespace=self.namespace, error=str(exc))
        # S3: 图谱"提及"边写入 (仅 enable_graph_recall=True 时; 不回填历史数据)。
        # 写边失败不影响 episode 已成功存储的结果, 只记 warning。
        if self._enable_graph_recall and memory_id:
            await self._write_mentioned_edges(memory_id, user_id, group_id, agent_id or self.namespace)
        if self._metrics is not None:
            self._metrics.counter("isac_memory_stores_total").inc()
        return memory_id

    async def _write_mentioned_edges(
        self, memory_id: str, user_id: str, group_id: str, agent_id: str
    ) -> None:
        """S3: 写入 user/group → episode 的"提及"边 (图召回种子)。

        失败只记 warning, 不影响 episode 已成功存储的结果。
        """
        try:
            if user_id:
                await self.graph.add_edge(
                    agent_id, f"user:{user_id}", "mentioned_in", f"episode:{memory_id}",
                )
            if group_id:
                await self.graph.add_edge(
                    agent_id, f"group:{group_id}", "mentioned_in", f"episode:{memory_id}",
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "图谱 mentioned_in 边写入失败, 已忽略",
                namespace=self.namespace, memory_id=memory_id, error=str(exc),
            )

    @staticmethod
    def _merge_results(
        fts_rows: list[dict],
        sparse_rows: list[tuple[str, float]],
        dense_rows: list[tuple[str, float]] | None = None,
        graph_rows: list[tuple[str, float]] | None = None,
    ) -> list[MemoryHit]:
        """RRF 融合 FTS / BM25 / 稠密 / 图谱四路召回 (CR3-H3 加入 dense_rows, S3 加入 graph_rows)。

        dense_rows 是 (memory_id, distance) 且按距离升序、graph_rows 是 (memory_id, weight)
        且按权重降序 —— RRF 只用名次不用原始分值, 与 FTS 路的贡献公式一致 (1/(60+rank));
        未经 get_episodes_by_ids 补齐行数据的候选 (被 ACL/软删过滤) 在末尾 rows_by_id
        检查中被丢弃。graph_rows 默认 None (未启用图谱召回时零贡献)。
        """
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
        for rank, (memory_id, _distance) in enumerate(dense_rows or [], start=1):
            scores[memory_id] = scores.get(memory_id, 0.0) + 1 / (60 + rank)
        for rank, (memory_id, _weight) in enumerate(graph_rows or [], start=1):
            scores[memory_id] = scores.get(memory_id, 0.0) + 1 / (60 + rank)
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
