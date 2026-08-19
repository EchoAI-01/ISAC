"""U2 服务装配 (wiring): build_services 与服务构造器 (LLM/多模态/会话内核/记忆/
租户/工具权限管线/用量)。原 main.py 拆出; 返回 ServiceContainer (核心键类型化)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from isac.dispatch import _noop_start
from isac.memory.embedder import EmbeddingManager
from isac.memory.pipeline import MemoryRetrievalPipeline, NoOpMemoryPipeline
from isac.memory.reranker import Reranker
from isac.memory.stack import _build_memory_stack
from isac.memory.storage.graph import GraphStore
from isac.memory.storage.metadata import MetadataStore
from isac.memory.storage.sparse import SparseBM25Index
from isac.memory.storage.vector import VectorStore
from isac.observability import get_default_metrics
from isac.observability.usage.stack import _build_usage_stack
from isac.provider.catalog import ModelCatalog, ModelDescriptor
from isac.provider.llm.openai_compat import OpenAICompatProvider
from isac.provider.llm.stub import StubProvider
from isac.provider.manager import ProviderManager
from isac.runtime.services import ServiceContainer
from isac.runtime.tenancy.manager import _build_tenant_manager
from isac.utils.logger import get_logger
from isac.utils.media import _build_media_normalizer
from isac.utils.security import SecretStore

logger = get_logger(__name__)

DATA_DIR = Path("data")

# J2: 多模态 Provider 按 kind 实例化 + 注册到 ProviderManager + ModelCatalog
# 每个 mm 配置字段: kind / provider / api_key / base_url / model / cost_tier / latency_tier
_MM_KIND_TO_OPERATIONS: dict[str, set[str]] = {
    "image_gen": {"image_gen"},
    "video_gen": {"video_gen"},
    "stt": {"stt"},
    "tts": {"tts"},
    "embed": {"embed"},
    "vision": {"vision"},
    "rerank": {"rerank"},
}

_MM_KIND_TO_MODALITIES: dict[str, tuple[set[str], set[str]]] = {
    "image_gen": ({"text"}, {"image"}),
    "video_gen": ({"text"}, {"video"}),
    "stt": ({"audio"}, {"text"}),
    "tts": ({"text"}, {"audio"}),
    "embed": ({"text"}, {"embedding"}),
    "vision": ({"image", "text"}, {"text"}),
    "rerank": ({"text"}, {"score"}),
}



def _build_secret_store() -> SecretStore | None:
    """R5: 构造 SecretStore (env ISAC_SECRET_KEY 设置时; 否则 None 走原明文路径)。

    SecretStore 仅在 env ISAC_SECRET_KEY 配置时可用 (AES-256-GCM 解密需要密钥)。
    未配置时返回 None, ``resolve_secret_async`` 对 ``secret:`` 前缀值原样回退 + warning,
    向后兼容 (旧明文配置零行为变化)。
    """
    import os

    if not os.environ.get("ISAC_SECRET_KEY"):
        return None
    return SecretStore(str(DATA_DIR / ".secrets.enc"))


def register_llm_provider(provider_manager: ProviderManager, llm_config: dict[str, Any]) -> None:
    """按配置注册 LLM Provider (K2, DEVELOPMENT_PLAN.md)。

    - llm.provider + llm.api_key 同时配置且 api_key 非占位符时注册 OpenAICompatProvider
      (真实 HTTP 实现), 不再静默降级为 Stub; 真实模型不可达时走 chat_with_retry 的降级回复
    - 未配置 / api_key 为占位符 (T1: "sk-your-key" 等 sample 占位值) 时用 StubProvider
      作为开发态兜底, 保证无 LLM 配置也能跑通主链路; Stub 回复含引导去配的提示

    T1: 此前只检查 api_key 非空, config.sample.jsonc 的 "sk-your-key" 被当有效 key
    注册 OpenAICompatProvider → 真实调用永远 401 → 用户看到"发消息收不到回复"且日志
    无明显错误。占位符检测把这类 sample 占位值视为未配置, 引导用户去配真实 key。
    """
    from isac.utils.config_schema import is_placeholder_key

    api_key = str(llm_config.get("api_key", "") or "")
    if llm_config.get("provider") and not is_placeholder_key(api_key):
        provider_manager.register(
            OpenAICompatProvider(
                api_key=api_key,
                base_url=str(llm_config.get("base_url", "")),
                model=str(llm_config.get("model", "")),
            ),
            # U7: provider_id 与 ModelDescriptor 键一致, category 路由据此取回实例
            provider_id=str(llm_config.get("provider", "") or "primary"),
            model_id=str(llm_config.get("model", "")),
        )
        logger.info(
            "已注册 OpenAICompatProvider",
            provider=llm_config.get("provider"),
            model=llm_config.get("model", ""),
            base_url=llm_config.get("base_url", ""),
        )
    else:
        provider_manager.register(StubProvider())
        logger.warning(
            "未配置有效 LLM api_key (为空或占位符), 使用 Stub 回复; "
            "请在 data/config.jsonc 的 llm 段填入真实 api_key 后重启",
            provider=llm_config.get("provider"),
            api_key_placeholder=is_placeholder_key(api_key),
        )


def _wire_llm_capabilities(services: ServiceContainer, global_config: dict[str, Any]) -> None:
    """U7: 能力快照接线 —— ModelRouter 注入 + primary LLM 描述符注册。

    ①provider_manager.model_router = model_router: chat_with_retry 成功/最终失败
    上报健康状态, 路由按可达性过滤 (record_health 从"定义未接线"转生产接线);
    ②primary LLM 注册 ModelDescriptor: supports_tools/模态从
    data/model_capabilities.json (models.dev 快照) 增强, cost/latency 档可经
    llm.cost_tier/latency_tier 配置。快照缺失时保守默认 (不阻塞, 仅路由精细度下降)。
    Stub 引导态不注册描述符 (不参与能力路由)。
    """
    from isac.provider.capabilities import CapabilitySnapshot

    provider_manager = services.provider_manager
    model_catalog = services.model_catalog
    if provider_manager is None or model_catalog is None:
        return
    model_router = services.model_router
    if model_router is not None:
        provider_manager.model_router = model_router

    llm_config = global_config.get("llm", {}) or {}
    provider = getattr(provider_manager, "_primary", None)
    provider_id = str(llm_config.get("provider") or "primary")
    if provider is None or not str(llm_config.get("model") or ""):
        return  # Stub 引导态/未配置模型: 不注册描述符
    model_id = str(llm_config.get("model"))

    snapshot = CapabilitySnapshot.load(DATA_DIR / "model_capabilities.json")
    cap = snapshot.get(provider_id, model_id)
    modalities_in = {"text"}
    supports_tools = False
    if cap is not None:
        supports_tools = bool(cap.supports_tools)
        modalities_in |= set(cap.modalities_in)
    operations = {"chat"}
    if "image" in modalities_in:
        operations.add("vision")
    cost_tier = str(llm_config.get("cost_tier") or "") or (cap.cost_tier if cap else "") or "standard"
    descriptor = ModelDescriptor(
        provider_id=provider_id,
        model_id=model_id,
        modalities_in=modalities_in,
        modalities_out={"text"},
        operations=operations,
        supports_tools=supports_tools,
        supports_streaming=True,
        cost_tier=cost_tier,
        latency_tier=str(llm_config.get("latency_tier") or "standard"),
    )
    model_catalog.register(descriptor)
    logger.info(
        "已注册 LLM 能力描述符",
        provider=provider_id,
        model=model_id,
        supports_tools=supports_tools,
        snapshot_hit=cap is not None,
        snapshot_models=len(snapshot),
    )


def _build_multimodal_provider(
    kind: str,
    api_key: str,
    base_url: str,
    model: str,
    artifact_store: Any,
    *,
    protocol: str = "cohere",
) -> Any | None:
    """按 kind 实例化多模态 Provider; 未知 kind 抛 ValueError。"""
    if kind == "image_gen":
        from isac.provider.image_gen.openai_compat import OpenAICompatImageGenProvider
        return OpenAICompatImageGenProvider(api_key, base_url, model, artifact_store)
    if kind == "video_gen":
        # S6 (O5): 视频生成注册挂点。默认配置无 video_gen 项 → 不构造 → 零行为变化;
        # Provider.generate 仍抛 NotImplementedError (端点开工前需二次确认), 注册本身
        # 不触发调用, 仅当 Agent 真正请求视频生成时才暴露"未实现"。构造参数顺序
        # (api_base, api_key) 与 image_gen 不同, 用关键字传参避免错位。
        from isac.provider.video_gen.openai_compat import OpenAICompatVideoGenProvider
        return OpenAICompatVideoGenProvider(
            api_base=base_url, api_key=api_key, model=model, artifact_store=artifact_store
        )
    if kind == "stt":
        from isac.provider.stt_tts.openai_compat import OpenAICompatSTTProvider
        return OpenAICompatSTTProvider(api_key, base_url, model)
    if kind == "tts":
        from isac.provider.stt_tts.openai_compat import OpenAICompatTTSProvider
        return OpenAICompatTTSProvider(api_key, base_url, model, artifact_store)
    if kind == "embed":
        from isac.provider.embed.openai_compat import OpenAICompatEmbeddingProvider
        return OpenAICompatEmbeddingProvider(api_key, base_url, model)
    if kind == "vision":
        # vision 走 LLM Provider 的 vision_chat 方法 (gpt-4o 兼容)
        return OpenAICompatProvider(api_key, base_url, model)
    if kind == "rerank":
        from isac.provider.rerank.openai_compat import OpenAICompatRerankerProvider
        return OpenAICompatRerankerProvider(api_key, base_url, model, protocol=protocol)
    raise ValueError(f"未知 multimodal kind: {kind}")


def register_multimodal_providers(
    provider_manager: ProviderManager,
    model_catalog: Any,
    artifact_store: Any,
    mm_list: list[dict[str, Any]] | None,
) -> None:
    """J2: 按 multimodal_providers[] 配置实例化并注册多模态 Provider + ModelDescriptor。

    缺 api_key/model/未知 kind 跳过 + 警告, 不抛异常阻塞主链路。
    """
    if not mm_list:
        return
    for mm in mm_list:
        kind = str(mm.get("kind", "")).strip()
        provider_id = str(mm.get("provider", "")).strip()
        api_key = str(mm.get("api_key", "")).strip()
        base_url = str(mm.get("base_url", "")).strip()
        model = str(mm.get("model", "")).strip()
        if not kind or not api_key or not model:
            logger.warning(
                "多模态 Provider 配置不完整, 跳过",
                kind=kind, provider=provider_id, has_api_key=bool(api_key), has_model=bool(model),
            )
            continue
        try:
            protocol = str(mm.get("protocol", "cohere"))
            provider = _build_multimodal_provider(
                kind, api_key, base_url, model, artifact_store, protocol=protocol
            )
        except ValueError as exc:
            logger.warning("多模态 Provider 构造失败, 跳过", kind=kind, error=str(exc))
            continue
        provider_manager.register_multimodal(
            provider, provider_id=provider_id, model_id=model
        )
        operations = _MM_KIND_TO_OPERATIONS.get(kind, set())
        modalities = _MM_KIND_TO_MODALITIES.get(kind, (set(), set()))
        descriptor = ModelDescriptor(
            provider_id=provider_id,
            model_id=model,
            operations=operations,
            modalities_in=modalities[0],
            modalities_out=modalities[1],
            cost_tier=str(mm.get("cost_tier", "standard")),
            latency_tier=str(mm.get("latency_tier", "standard")),
        )
        model_catalog.register(descriptor)
        logger.info(
            "已注册多模态 Provider",
            kind=kind, provider=provider_id, model=model,
            cost_tier=descriptor.cost_tier, latency_tier=descriptor.latency_tier,
        )




def _build_session_history_kernel(global_config: dict[str, Any]) -> tuple[Any, Any]:
    """U1: 构造事件溯源会话内核 (SessionEventStore + SessionHistoryDeriver)。

    session.history 配置节: enabled (默认 True) / window_turns (默认 10) /
    budget_tokens (默认 None)。store 落 data/gateway/session_events.db (WAL)。
    返回 (store, deriver); enabled=false 时仍构造 (由 manager 侧 _session_history_enabled
    判定, 便于测试注入) —— 真正不启用时在 manager 返回空历史, 零行为变化。
    """
    from isac.session.event_store import SessionEventStore
    from isac.session.history import SessionHistoryDeriver

    hist_cfg = global_config.get("session", {}).get("history", {}) or {}

    def _int(key: str, default: int) -> int:
        try:
            return max(1, int(hist_cfg.get(key, default) or default))
        except (TypeError, ValueError):
            return default

    store = SessionEventStore(str(DATA_DIR / "gateway" / "session_events.db"))
    budget_raw = hist_cfg.get("budget_tokens")
    try:
        budget_tokens = int(budget_raw) if budget_raw else None
    except (TypeError, ValueError):
        budget_tokens = None
    deriver = SessionHistoryDeriver(window_turns=_int("window_turns", 10), budget_tokens=budget_tokens)
    return store, deriver


def _build_tool_permission_pipeline(global_config: dict[str, Any]) -> tuple[Any, Any]:
    """U5: 构造工具权限管线组件 (ApprovalGate + DenyGuard)。

    tools.approval 配置节: timeout_seconds (默认 300, 下限 5)。ask 档工具执行前
    经 ApprovalGate 等待人工"同意/拒绝", 超时 fail-closed; DenyGuard 记录会话内
    被拒工具 (拒绝不可翻回), 启动时从 U1 事件流重建。返回 (approval_gate, deny_guard)。
    """
    from isac.agent.tools.approval import ApprovalGate
    from isac.agent.tools.guard import DenyGuard

    approval_cfg = global_config.get("tools", {}).get("approval", {}) or {}
    try:
        timeout_seconds = float(approval_cfg.get("timeout_seconds", 300) or 300)
    except (TypeError, ValueError):
        timeout_seconds = 300.0
    return ApprovalGate(timeout_seconds=timeout_seconds), DenyGuard()


def build_services(global_config: dict[str, Any]) -> ServiceContainer:
    """构建共享服务字典 (供 AgentManager 组装 AgentInstance)。

    metrics 是应用生命周期内唯一的 MetricsCollector 实例, 通过这个 services 字典
    注入给 AgentManager/ISACAgentLoop (二者已持有 services), 并显式传给 ProviderManager/
    MemoryRetrievalPipeline (CODE_REVIEW_REPORT.md #5)。
    """
    metrics = get_default_metrics()

    usage_store, usage_recorder = _build_usage_stack(global_config)

    provider_manager = ProviderManager(global_config.get("llm", {}), metrics=metrics, usage_recorder=usage_recorder)
    memory_config = global_config.get("memory", {})
    metadata_store: MetadataStore | None = None
    graph_store: GraphStore | None = None
    sparse_indexes: dict[str, SparseBM25Index] = {}
    # CR3 复核修正: VectorStore 按 namespace 分库 (vectors-<ns>.db)。此前全部
    # Agent 共享单一 vec0 表做全库 KNN, 其他命名空间的向量会挤占 top-K 召回
    # 槽位 (ACL 过滤后被丢弃且不回补), 多 Agent 下稠密召回系统性退化为空。
    # 旧共享 vectors.db 无迁移负担: CR3 之前生产 embedder 从未注入 provider,
    # 该文件不会有数据。
    vector_stores: dict[str, VectorStore] = {}
    embedder: EmbeddingManager | None = None
    reranker: Reranker | None = None

    # CR3-L2 (O1/P5): 租户隔离接线。默认 tenancy.enabled=false → guard passthrough
    # + 默认租户, 单租户部署零行为变化; enabled=true 时记忆命名空间加租户前缀,
    # MetadataStore 读写带租户谓词/打标 (跨租户共享同一 DB 文件时互不可见)。
    from isac.runtime.tenancy.isolation import TenantIsolationGuard, warn_if_default_tenant_fail_open
    from isac.runtime.tenancy.models import DEFAULT_ORG, DEFAULT_TENANT, TenantContext

    tenancy_config = global_config.get("tenancy", {}) or {}
    tenant_guard = TenantIsolationGuard(enabled=bool(tenancy_config.get("enabled")))
    tenant_context = TenantContext(
        organization_id=str(tenancy_config.get("organization_id") or DEFAULT_ORG),
        tenant_id=str(tenancy_config.get("tenant_id") or DEFAULT_TENANT),
    )
    warn_if_default_tenant_fail_open(tenant_guard, tenant_context)
    # R6-①: TenantManager (租户 CRUD + 成员, SQLite)。抽 helper 降 build_services 复杂度。
    # tenancy.enabled 时构造并传入控制面 routes_tenants; 默认关闭 → None → 路由不挂载。
    tenant_manager = _build_tenant_manager(tenancy_config, memory_config)

    if memory_config.get("enabled"):
        metadata_store, graph_store, embedder, reranker = _build_memory_stack(
            memory_config, tenant_guard, tenant_context, usage_recorder
        )

    async def _storage_start() -> None:
        """K3: 启动时执行 SQLite schema init/migration (MetadataStore.init_schema);
        VectorStore 按 namespace 惰性创建, schema 在首次 upsert/search 时自建;
        memory 关闭时由各 store 的 async-with 自行释放, 无显式 close 动作
        (aiosqlite 每次连接即关)。"""
        if metadata_store is not None:
            await metadata_store.init_schema()
            logger.info("MetadataStore schema 已初始化", path=metadata_store.db_path)

    def _vector_store_for(namespace: str) -> VectorStore:
        """按 namespace 惰性创建独立 VectorStore (vectors-<safe_ns>.db)。"""
        store = vector_stores.get(namespace)
        if store is None:
            import hashlib
            import re as _re

            safe = _re.sub(r"[^A-Za-z0-9_-]", "_", namespace) or "default"
            if safe != namespace:
                # 含非法文件名字符 (如租户前缀的 ":") 时加短哈希防替换后碰撞
                safe = f"{safe}-{hashlib.sha256(namespace.encode('utf-8')).hexdigest()[:8]}"
            store = VectorStore(
                str(DATA_DIR / "memory" / f"vectors-{safe}.db"),
                dimension=int(memory_config.get("embedding", {}).get("dimension", 1024) or 1024),
            )
            vector_stores[namespace] = store
        return store

    def memory_factory(namespace: str) -> Any:
        # CR3-L2: 多租户启用时命名空间加 org:tenant 前缀 (默认租户原样返回)
        namespace = tenant_guard.namespace_for(namespace, tenant_context)
        if not memory_config.get("enabled"):
            return NoOpMemoryPipeline(namespace)
        assert metadata_store is not None
        assert graph_store is not None
        assert embedder is not None
        sparse = sparse_indexes.setdefault(namespace, SparseBM25Index())
        return MemoryRetrievalPipeline(
            namespace=namespace,
            metadata=metadata_store,
            vector=_vector_store_for(namespace),
            sparse=sparse,
            graph=graph_store,
            embedder=embedder,
            reranker=reranker,
            metrics=metrics,
            # S3: 图谱邻居召回开关 (默认关闭; 骨架期即使开启也零产出, 零行为变化)。
            enable_graph_recall=bool(memory_config.get("graph_recall", {}).get("enabled", False)),
        )

    # J2: 模型能力目录 / 路由 / 制品存储 (轻量, 始终构造, 无 I/O 副作用)。
    # 默认无多模态 Provider 注册 → ModelRouter.select 返回 None, Agent 无多模态能力;
    # 用户在 config.jsonc 的 multimodal_providers[] 配置 api_key/base_url/model 后,
    # register_multimodal_providers 实例化 Provider 并注册到 catalog + provider_manager。
    from isac.artifacts.store import ArtifactStore
    from isac.provider.router import ModelRouter

    model_catalog = ModelCatalog()
    model_router = ModelRouter(model_catalog)
    artifact_store = ArtifactStore(str(DATA_DIR / "artifacts"))
    # R1-②: 入站媒体下载落盘专用 ArtifactStore (与出站 artifacts 分目录, TTL 独立)。
    uploads_store = ArtifactStore(str(DATA_DIR / "uploads"))
    # R1-②: MediaNormalizer 白名单含 data/uploads (抽 helper 降 build_services 复杂度)
    media_normalizer = _build_media_normalizer(global_config)

    # J2: 按 global_config.multimodal_providers[] 注册真实 Provider + ModelDescriptor
    # 缺 api_key/model/未知 kind 跳过 + 警告, 不阻塞主链路
    register_multimodal_providers(
        provider_manager, model_catalog, artifact_store,
        global_config.get("multimodal_providers"),
    )

    # J4: SubAgent 运行时。Supervisor 轻量常驻 (纯内存); Journal 持久化默认关闭,
    # subagent.enabled=true 时才创建 DB 与生命周期。生产 runner 在 AgentManager 创建后绑定。
    from isac.runtime.subagent.supervisor import SubAgentSupervisor

    subagent_journal: Any = None
    if (global_config.get("subagent", {}) or {}).get("enabled"):
        from isac.runtime.subagent.journal import SubAgentJournal

        subagent_journal = SubAgentJournal(str(DATA_DIR / "subagent" / "journal.db"))
    subagent_supervisor = SubAgentSupervisor(journal=subagent_journal)

    # R3: CLI 工具 (bash/read_file/write_file) 后端注入。此前 build_services 不注入
    # workspace_root/bash_allowlist → 三工具恒因 services 未注入被拒 (即使
    # tools_policy allow 也调不通)。默认 workspace_root=data/workspace (LLM 文件
    # 操作沙箱, mkdir 确保存在); bash_allowlist 默认空 (禁止所有命令, 需显式配置)。
    tools_config = global_config.get("tools", {}) or {}
    workspace_root = str(DATA_DIR / "workspace")
    (DATA_DIR / "workspace").mkdir(parents=True, exist_ok=True)

    # U2: ServiceContainer (dict 子类, 核心键类型化属性, 键错配类型层不可能)
    return ServiceContainer({
        "global_config": global_config,
        "provider_manager": provider_manager,
        "memory_factory": memory_factory,
        "metrics": metrics,
        "storage_start": _storage_start if memory_config.get("enabled") else _noop_start,
        # CR3: 记忆存储句柄 (memory 未启用时为 None)。此前 services 里根本没有
        # "metadata_store" 键, _register_control_plane 按字符串键取值恒 None,
        # routes_memory / routes_memory_admin / routes_sessions 在生产从未挂载。
        "metadata_store": metadata_store,
        "sparse_indexes": sparse_indexes,
        # R7/R8: vector_resolver 让治理 delete/correct/restore 同步稠密向量行
        # (防止软删除后向量残留污染召回); graph_store 让 _purge_memory 清理
        # 该 namespace 的全部 edges (重建同名 Agent 不被旧 edges 污染)。
        "vector_resolver": _vector_store_for,
        "graph_store": graph_store,
        # C1: shutdown 时遍历 vector_stores 关闭持久连接
        "vector_stores": vector_stores,
        # CR3-L2: 租户上下文 (默认单租户 passthrough)
        "tenant_guard": tenant_guard,
        "tenant_context": tenant_context,
        # R6-①: 租户 CRUD 管理器 (tenancy.enabled 时构造, 否则 None)
        "tenant_manager": tenant_manager,
        # J1: 计量子系统句柄 (未启用时为 None, main 据此决定是否注册生命周期)。
        "usage_store": usage_store,
        "usage_recorder": usage_recorder,
        # J2: 模型能力目录 / 路由 / 制品存储 (供多模态工具与能力选择使用)。
        "model_catalog": model_catalog,
        "model_router": model_router,
        "artifact_store": artifact_store,
        "uploads_store": uploads_store,
        "media_normalizer": media_normalizer,
        # J4: SubAgent 监督器 (常驻) 与日志句柄 (未启用时为 None)。
        "subagent_supervisor": subagent_supervisor,
        "subagent_journal": subagent_journal,
        # R3: CLI 工具后端 (bash/read_file/write_file 经 ToolContext.services 取用)
        "workspace_root": workspace_root,
        "bash_allowlist": list(tools_config.get("bash_allowlist") or []),
        # R3: 全局 MCP Server 定义 (name → {transport,command,args,env,url,token}),
        # config.jsonc 顶层 mcp.servers 节。assemble_agent 按 AgentConfig.mcp_servers
        # (允许名列表) 查此定义构造 MCPClient。默认空, 零行为变化。
        "mcp_servers": (global_config.get("mcp", {}) or {}).get("servers", {}) or {},
    })
