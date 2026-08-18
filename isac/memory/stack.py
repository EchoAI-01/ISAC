"""U2 记忆子系统构造器: metadata/graph 存储 + embedding/rerank 管理器。

原 isac/main.py 的 _build_memory_stack 归位记忆层 (U2 装配层重构)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from isac.memory.embedder import EmbeddingManager
from isac.memory.reranker import Reranker
from isac.memory.storage.graph import GraphStore
from isac.memory.storage.metadata import MetadataStore
from isac.utils.logger import get_logger

logger = get_logger(__name__)

DATA_DIR = Path("data")

def _build_memory_stack(
    memory_config: dict[str, Any],
    tenant_guard: Any,
    tenant_context: Any,
    usage_recorder: Any = None,
) -> tuple[MetadataStore, GraphStore, EmbeddingManager, Reranker]:
    """构造记忆子系统 (memory.enabled=true 时): 元数据/图谱存储 + 嵌入/重排管理器。

    CR3-H3: memory.embedding 配置了 api_key+model 时注入真实 EmbeddingProvider
    —— 此前 EmbeddingManager 从不注入 provider, 生产恒降级 (is_degraded=True),
    写入白算 embedding、检索永远走不到稠密召回。
    """
    memory_dir = DATA_DIR / "memory"
    metadata_store = MetadataStore(
        str(memory_dir / "metadata.db"),
        tenant_guard=tenant_guard,
        tenant_context=tenant_context,
    )
    graph_store = GraphStore(str(memory_dir / "graph.db"))
    embedding_config = memory_config.get("embedding", {}) or {}
    embedding_provider = None
    if embedding_config.get("api_key") and embedding_config.get("model"):
        from isac.provider.embed.openai_compat import OpenAICompatEmbeddingProvider

        embedding_provider = OpenAICompatEmbeddingProvider(
            str(embedding_config.get("api_key")),
            str(embedding_config.get("base_url", "") or ""),
            str(embedding_config.get("model")),
        )
        logger.info(
            "已注入记忆 EmbeddingProvider (稠密召回启用)",
            model=embedding_config.get("model"),
            base_url=embedding_config.get("base_url", ""),
        )
    embedder = EmbeddingManager(embedding_config, provider=embedding_provider, usage_recorder=usage_recorder)
    # S3: Reranker provider 注入 (仿 CR3-H3 embedding 写法) —— 此前 main 构造
    # Reranker(memory_config.get("reranker", {})) 时从未传入 provider, is_available()
    # 恒 False, rerank 步骤永不执行。配置 reranker.api_key+model 即启用真实 HTTP。
    reranker_provider = None
    reranker_config = memory_config.get("reranker", {}) or {}
    if reranker_config.get("api_key") and reranker_config.get("model"):
        from isac.provider.rerank.openai_compat import OpenAICompatRerankerProvider

        reranker_provider = OpenAICompatRerankerProvider(
            str(reranker_config.get("api_key")),
            str(reranker_config.get("base_url", "") or ""),
            str(reranker_config.get("model")),
            protocol=str(reranker_config.get("protocol", "cohere")),
        )
        logger.info(
            "已注入记忆 RerankerProvider (rerank 启用)",
            model=reranker_config.get("model"),
            base_url=reranker_config.get("base_url", ""),
        )
    reranker = Reranker(reranker_config, provider=reranker_provider, usage_recorder=usage_recorder)
    return metadata_store, graph_store, embedder, reranker
