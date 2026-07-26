"""ISAC 应用入口: 组装所有组件 + 依赖注入 (DEVELOP.md 1.2)。

组装顺序遵循导入依赖链:
utils → provider → memory → persona → agent → gating → router
→ gateway → channel → commands → plugin → runtime → control
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from isac.channel.model import ISACMessage
from isac.channel.registry import ChannelRegistry
from isac.core.events import EventType
from isac.core.types import ProgressEvent
from isac.gateway.event_bus import EventBus
from isac.gateway.lock import SessionLockManager
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.memory.embedder import EmbeddingManager
from isac.memory.pipeline import MemoryRetrievalPipeline, NoOpMemoryPipeline
from isac.memory.reranker import Reranker
from isac.memory.storage.graph import GraphStore
from isac.memory.storage.metadata import MetadataStore
from isac.memory.storage.sparse import SparseBM25Index
from isac.memory.storage.vector import VectorStore
from isac.observability import AlertManager, MetricsCollector, get_default_alert_rules, get_default_metrics
from isac.provider.catalog import ModelCatalog, ModelDescriptor
from isac.provider.llm.openai_compat import OpenAICompatProvider
from isac.provider.llm.stub import StubProvider
from isac.provider.manager import ProviderManager
from isac.router.router import MessageRouter
from isac.router.rules import load_rules
from isac.runtime.application import ApplicationRuntime
from isac.runtime.bus import InterAgentBus, InterAgentLink, InterAgentMessage
from isac.runtime.manager import AgentManager, ensure_default_agent, load_persisted_agents
from isac.utils.config import load_config
from isac.utils.logger import get_logger, setup_logger

logger = get_logger(__name__)

DATA_DIR = Path("data")


async def process_message(
    message: ISACMessage,
    *,
    event_bus: EventBus,
    router: MessageRouter,
    session_mgr: SessionManager,
    user_mapper: UserMapper,
    agent_manager: AgentManager,
    channel_registry: ChannelRegistry,
    metrics: MetricsCollector | None = None,
) -> None:
    """消息主链路: EventBus → Router → Agent (DEVELOP.md 1.2 依赖注入)。"""
    metrics = metrics or get_default_metrics()
    metrics.counter("isac_messages_received_total").inc()

    payload = await event_bus.fire_intercept(EventType.ON_MESSAGE, message)
    if payload is None:
        metrics.counter("isac_messages_dropped_total").inc()
        return  # 被插件拦截
    message = payload

    decision = await router.route(message)
    if decision is None:
        metrics.counter("isac_messages_dropped_total").inc()
        return  # 路由无匹配 → DROP
    routed_message = dataclasses.replace(message, content=decision.content)

    # Q0: 在 get_or_create 改写 session_id 为内部 sess_* 之前, 捕获适配器侧的
    # 平台会话键 (如 WebChat 客户端自带的 session_id)。出站回复/进度帧必须用
    # 平台键路由, 否则 WebChat 队列键与客户端轮询键对不上, 回复永远取不到。
    platform_session_id = routed_message.session_id
    session = await session_mgr.get_or_create(routed_message, agent_id=decision.agent_id)
    profile = await user_mapper.resolve(routed_message.platform, routed_message.user_id, routed_message.user_name)
    progress_sender = _make_progress_sender(
        channel_registry, routed_message, decision.agent_id, platform_session_id
    )
    try:
        reply = await agent_manager.handle_message(
            decision.agent_id, routed_message, session, profile, progress_sender=progress_sender
        )
    except Exception:
        metrics.counter("isac_messages_failed_total").inc()
        raise
    metrics.counter("isac_messages_processed_total").inc()
    if reply:
        await _send_reply(channel_registry, routed_message, reply, decision.agent_id, platform_session_id)
    await event_bus.fire_async(EventType.POST_MESSAGE, routed_message)


async def _send_reply(
    channel_registry: ChannelRegistry,
    incoming: ISACMessage,
    reply_text: str,
    agent_id: str,
    platform_session_id: str = "",
) -> None:
    """把 Agent 的文本回复经原 Channel 适配器发送。

    Q0: platform_session_id 是 gateway 改写前的适配器侧会话键 (WebChat 客户端
    的 session_id); 出站按平台键路由, 客户端才能按自己的键轮询到回复。适配器
    未提供平台键时 (OneBot 等按 group/user 路由的平台) 回退内部 session_id。
    """
    adapter = channel_registry.get(incoming.platform)
    if adapter is None:
        logger.warning("未找到对应平台适配器，无法发送回复", platform=incoming.platform, agent_id=agent_id)
        return

    reply = ISACMessage(
        msg_id="",  # 发送后由平台分配
        platform=incoming.platform,
        timestamp=0,
        user_id=incoming.user_id,
        user_name="",  # 发送方是 Bot，无需昵称
        group_id=incoming.group_id,
        session_id=platform_session_id or incoming.session_id,
        content=reply_text,
        reply_to=incoming.msg_id,
    )
    success = await adapter.send(reply)
    if not success:
        logger.warning("回复发送失败", platform=incoming.platform, agent_id=agent_id)
    else:
        logger.info("Agent 回复已发送", agent_id=agent_id, platform=incoming.platform, length=len(reply_text))


def _make_progress_sender(
    channel_registry: ChannelRegistry, incoming: ISACMessage, agent_id: str, platform_session_id: str = ""
) -> Callable[[str, ProgressEvent], Awaitable[None]]:
    """D9: 构造绑定到本次到达消息所属 Channel 的进度 sender。

    与 _send_reply 同构: 按 incoming.platform 找 adapter, 构造一条降级为普通文本的
    ISACMessage, 附 metadata.message_kind=progress 供 Channel 侧按需特殊处理
    (WebChat 输出原生 kind 字段, 其余平台按普通文本发送)。找不到 adapter / 发送失败
    时只记日志, 不得影响主任务 (进度是旁路信号)。
    Q0: 与 _send_reply 一致改用 platform_session_id (gateway 改写前的平台会话键)
    路由, WebChat 进度帧此前落在内部 sess_* 键下, 客户端同样轮询不到。
    """

    async def sender(text: str, event: ProgressEvent) -> None:
        adapter = channel_registry.get(incoming.platform)
        if adapter is None:
            return
        progress_message = ISACMessage(
            msg_id="",
            platform=incoming.platform,
            timestamp=0,
            user_id=incoming.user_id,
            user_name="",
            group_id=incoming.group_id,
            session_id=platform_session_id or incoming.session_id,
            content=text,
            reply_to=incoming.msg_id,
            metadata={"message_kind": "progress", "task_id": event.task_id, "progress_stage": event.stage},
        )
        try:
            await adapter.send(progress_message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("进度通知发送失败, 已忽略", platform=incoming.platform, agent_id=agent_id, error=str(exc))

    return sender


def _register_channel_adapters(channel_registry: ChannelRegistry, global_config: dict[str, Any]) -> None:
    """Q0: 按 channels.* 配置注册各平台适配器。

    此前生产入口只有 OneBot 一个注册分支, Telegram/Discord/WebChat 三个适配器
    实现+单测齐全却零调用点 (开箱只有需要外部 NapCat 的 QQ 一条可聊通道)。
    全部惰性导入: 未启用的平台不 import 对应模块, 可选依赖不成为强制依赖。
    """
    channels_config = global_config.get("channels", {}) or {}

    onebot_config = channels_config.get("onebot")
    if onebot_config and onebot_config.get("enabled"):
        from isac.channel.adapters.onebot.adapter import OneBotAdapter

        channel_registry.register(OneBotAdapter(onebot_config))
    telegram_config = channels_config.get("telegram")
    if telegram_config and telegram_config.get("enabled"):
        from isac.channel.adapters.telegram.adapter import TelegramAdapter

        channel_registry.register(TelegramAdapter(telegram_config))
    discord_config = channels_config.get("discord")
    if discord_config and discord_config.get("enabled"):
        from isac.channel.adapters.discord.adapter import DiscordAdapter

        channel_registry.register(DiscordAdapter(discord_config))
    webchat_config = channels_config.get("webchat")
    if webchat_config and webchat_config.get("enabled"):
        from isac.channel.adapters.webchat.adapter import WebChatAdapter

        channel_registry.register(WebChatAdapter(webchat_config))
    registered = [adapter.platform_name for adapter in channel_registry.list()]
    if registered:
        logger.info("Channel 适配器已注册", platforms=registered)
    else:
        logger.info("未启用任何 Channel 适配器 (channels.* 均未 enabled)")


def _ensure_default_routing(router: MessageRouter, channel_registry: ChannelRegistry, fallback_agent_id: str) -> None:
    """Q0: 裸部署 (未配置任何路由规则) 时为每个已注册平台登记默认 Agent。

    此前无 data/routing.jsonc 时所有无触发词消息在 router 层全部 DROP, 新用户
    首跑收不到任何回复。仅在规则完全为空 (无 bindings 且无 default_agents) 时
    兜底 —— 用户显式配置过任何路由即完全不动, 保留有意的 DROP 语义; 只改内存
    规则不落盘, 不把隐式默认写进用户配置文件。
    """
    rules = router.get_rules()
    if rules.bindings or rules.default_agents:
        return
    platforms = [adapter.platform_name for adapter in channel_registry.list()]
    if not platforms:
        return
    for platform in platforms:
        rules.default_agents[platform] = fallback_agent_id
    router.set_rules(rules)
    logger.info(
        "未配置任何路由规则, 已为已启用平台登记默认 Agent (仅内存, 不落盘)",
        platforms=platforms,
        agent_id=fallback_agent_id,
    )


def register_llm_provider(provider_manager: ProviderManager, llm_config: dict[str, Any]) -> None:
    """按配置注册 LLM Provider (K2, DEVELOPMENT_PLAN.md)。

    - llm.provider + llm.api_key 同时配置时注册 OpenAICompatProvider (真实 HTTP 实现),
      不再静默降级为 Stub; 真实模型不可达时走 chat_with_retry 的降级回复
    - 未配置任何 Provider 时用 StubProvider 作为开发态兜底, 保证无 LLM 配置也能跑通主链路
    """
    if llm_config.get("provider") and llm_config.get("api_key"):
        provider_manager.register(
            OpenAICompatProvider(
                api_key=str(llm_config.get("api_key", "")),
                base_url=str(llm_config.get("base_url", "")),
                model=str(llm_config.get("model", "")),
            )
        )
        logger.info(
            "已注册 OpenAICompatProvider",
            provider=llm_config.get("provider"),
            model=llm_config.get("model", ""),
            base_url=llm_config.get("base_url", ""),
        )
    else:
        provider_manager.register(StubProvider())


# J2: 多模态 Provider 按 kind 实例化 + 注册到 ProviderManager + ModelCatalog
# 每个 mm 配置字段: kind / provider / api_key / base_url / model / cost_tier / latency_tier
_MM_KIND_TO_OPERATIONS: dict[str, set[str]] = {
    "image_gen": {"image_gen"},
    "stt": {"stt"},
    "tts": {"tts"},
    "embed": {"embed"},
    "vision": {"vision"},
    "rerank": {"rerank"},
}

_MM_KIND_TO_MODALITIES: dict[str, tuple[set[str], set[str]]] = {
    "image_gen": ({"text"}, {"image"}),
    "stt": ({"audio"}, {"text"}),
    "tts": ({"text"}, {"audio"}),
    "embed": ({"text"}, {"embedding"}),
    "vision": ({"image", "text"}, {"text"}),
    "rerank": ({"text"}, {"score"}),
}


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


def build_services(global_config: dict[str, Any]) -> dict[str, Any]:
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
    from isac.runtime.tenancy.isolation import TenantIsolationGuard
    from isac.runtime.tenancy.models import DEFAULT_ORG, DEFAULT_TENANT, TenantContext

    tenancy_config = global_config.get("tenancy", {}) or {}
    tenant_guard = TenantIsolationGuard(enabled=bool(tenancy_config.get("enabled")))
    tenant_context = TenantContext(
        organization_id=str(tenancy_config.get("organization_id") or DEFAULT_ORG),
        tenant_id=str(tenancy_config.get("tenant_id") or DEFAULT_TENANT),
    )

    if memory_config.get("enabled"):
        metadata_store, graph_store, embedder, reranker = _build_memory_stack(
            memory_config, tenant_guard, tenant_context
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
        )

    # J2: 模型能力目录 / 路由 / 制品存储 (轻量, 始终构造, 无 I/O 副作用)。
    # 默认无多模态 Provider 注册 → ModelRouter.select 返回 None, Agent 无多模态能力;
    # 用户在 config.jsonc 的 multimodal_providers[] 配置 api_key/base_url/model 后,
    # register_multimodal_providers 实例化 Provider 并注册到 catalog + provider_manager。
    from isac.artifacts.store import ArtifactStore
    from isac.provider.router import ModelRouter
    from isac.utils.media import MediaNormalizer

    model_catalog = ModelCatalog()
    model_router = ModelRouter(model_catalog)
    artifact_store = ArtifactStore(str(DATA_DIR / "artifacts"))
    # 安全修复: transcribe_audio/understand_image 等工具必须先经 MediaNormalizer
    # 校验 media_uri (白名单目录 + MIME + 大小上限), 不能直接信任 LLM 工具调用参数
    # 里的任意绝对路径 (否则可读取白名单外的任意本地文件, 如 ~/.ssh/id_rsa)。
    media_normalizer = MediaNormalizer(global_config.get("media_normalizer") or {})

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

    return {
        "global_config": global_config,
        "provider_manager": provider_manager,
        "memory_factory": memory_factory,
        "metrics": metrics,
        "storage_start": _storage_start if memory_config.get("enabled") else _noop_start,
        # CR3: 记忆存储句柄 (memory 未启用时为 None)。此前 services 里根本没有
        # "metadata_store" 键, _register_control_plane 的 services.get() 恒 None,
        # routes_memory / routes_memory_admin / routes_sessions 在生产从未挂载。
        "metadata_store": metadata_store,
        "sparse_indexes": sparse_indexes,
        # CR3-L2: 租户上下文 (默认单租户 passthrough)
        "tenant_guard": tenant_guard,
        "tenant_context": tenant_context,
        # J1: 计量子系统句柄 (未启用时为 None, main 据此决定是否注册生命周期)。
        "usage_store": usage_store,
        "usage_recorder": usage_recorder,
        # J2: 模型能力目录 / 路由 / 制品存储 (供多模态工具与能力选择使用)。
        "model_catalog": model_catalog,
        "model_router": model_router,
        "artifact_store": artifact_store,
        "media_normalizer": media_normalizer,
        # J4: SubAgent 监督器 (常驻) 与日志句柄 (未启用时为 None)。
        "subagent_supervisor": subagent_supervisor,
        "subagent_journal": subagent_journal,
    }


def _build_usage_stack(global_config: dict[str, Any]) -> tuple[Any, Any]:
    """J1: 模型用量计量子系统 (默认关闭; observability.usage.enabled=true 时启用)。

    未启用时返回 (None, None) → ProviderManager 不计量, 主链路热路径零变化,
    也不会创建任何 usage.db 文件。
    """
    usage_config = (global_config.get("observability", {}) or {}).get("usage", {}) or {}
    if not usage_config.get("enabled"):
        return None, None
    from isac.observability.usage.pricing import PricingCatalog
    from isac.observability.usage.recorder import UsageRecorder
    from isac.observability.usage.storage import UsageStore

    usage_store = UsageStore(str(DATA_DIR / "usage" / "usage.db"))
    usage_recorder = UsageRecorder(
        store=usage_store,
        pricing=PricingCatalog(),
        flush_interval_seconds=float(usage_config.get("flush_interval_seconds", 30)),
    )
    return usage_store, usage_recorder


def _build_memory_stack(
    memory_config: dict[str, Any],
    tenant_guard: Any,
    tenant_context: Any,
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
    embedder = EmbeddingManager(embedding_config, provider=embedding_provider)
    reranker = Reranker(memory_config.get("reranker", {}))
    return metadata_store, graph_store, embedder, reranker


async def _noop_start() -> None:
    """无启动动作的资源 (如 Provider 连接池: 惰性创建, 无需 start) 占位。"""
    return None


async def main() -> None:
    """应用主入口。

    使用 ApplicationRuntime 统一管理后台任务生命周期 (K1, DEVELOPMENT_PLAN.md):
    - Channel/Control/Alert 等资源 register_lifecycle 成对注册, 启动按注册顺序、
      关闭按 LIFO 倒序
    - 后台 task 通过 runtime.spawn 挂到统一 TaskGroup, 持有强引用不被 GC
    - SIGINT/SIGTERM 触发 request_stop(), 进入优雅关闭
    - 之前 main 调 channel_registry.start_all() 后直接返回, 后台 task 随事件循环
      结束被取消的 bug 已修 (CODE_REVIEW_REPORT.md #12/#13)
    """
    global_config = load_config(DATA_DIR / "config.jsonc")
    _logging_cfg = global_config.get("logging", {}) or {}
    # debug=true 视为全局 DEBUG; 否则用 log_level / logging.level; 均缺省时 setup_logger 落 INFO。
    _level = "debug" if global_config.get("debug") else (global_config.get("log_level") or _logging_cfg.get("level"))
    setup_logger(
        debug=bool(global_config.get("debug", False)),
        log_format=_logging_cfg.get("format", "console"),
        level=_level,
        per_module=_logging_cfg.get("per_module"),
    )
    logger.info("ISAC 启动中", version=_get_version())

    runtime = ApplicationRuntime()
    runtime.install_signal_handlers()

    # ── Provider ────────────────────────────────────────────
    services = build_services(global_config)
    metrics: MetricsCollector = services["metrics"]
    register_llm_provider(services["provider_manager"], global_config.get("llm", {}))

    # ── Runtime (Agent 管理 + 互联总线) ─────────────────────
    agent_manager = AgentManager(services)
    from isac.runtime.subagent.runner import configure_subagent_runner

    configure_subagent_runner(services["subagent_supervisor"], agent_manager)
    bus = InterAgentBus()
    # 投递回调: 把 InterAgentMessage 路由到目标 Agent 的 handle_message。
    # 命令 (ask_agent) 现在能拿到 response 而不是恒 None (CODE_REVIEW_REPORT.md #3)。
    async def _deliver_to_agent(target_agent_id: str, message: InterAgentMessage) -> str | None:
        # 互联消息复用原消息的 session 上下文; 跨 Agent 时把 from_agent 当作 user_id
        # 让目标 Agent 不会因 has_at=False 而被门控过滤。但目标 Agent 的 handle_message
        # 依赖真实 Session/UserProfile; 这里构造一个最小可路由会话。
        wrapped = ISACMessage(
            msg_id="",
            platform="interagent",
            timestamp=0,
            user_id=message.from_agent,
            user_name="",
            group_id=None,
            content=message.content,
        )
        session_mgr = SessionManager(global_config)
        session = await session_mgr.get_or_create(wrapped, agent_id=target_agent_id)
        return await agent_manager.handle_message(target_agent_id, wrapped, session, None)

    bus.set_deliver(_deliver_to_agent)
    # 启动时从 data/links.jsonc 恢复已持久化的互联 Link (CODE_REVIEW_REPORT.md #3)。
    await _load_persisted_links(bus, DATA_DIR / "links.jsonc")
    # Link 持久化回调: add_link/remove_link 改动时落盘 (失败只记日志, 不回滚 in-memory)。
    def _persist_links_snapshot() -> None:
        from isac.control.api.routes_routing import _persist_links

        _persist_links(bus, DATA_DIR / "links.jsonc")

    bus.set_persist(_persist_links_snapshot)
    # 把 bus 也加入 services, 让 ask_agent 工具与命令能通过 context.services 访问。
    services["bus"] = bus

    # ── Router (Channel 与 Agent 解耦) ──────────────────────
    rules = load_rules(global_config.get("router", {}).get("rules_file", DATA_DIR / "routing.jsonc"))
    router = MessageRouter(rules, agents_provider=agent_manager.routing_infos)

    # ── Channel ─────────────────────────────────────────────
    channel_registry = ChannelRegistry()
    _register_channel_adapters(channel_registry, global_config)

    # ── Gateway ─────────────────────────────────────────────
    event_bus = EventBus()
    session_mgr = SessionManager(global_config)
    user_mapper = UserMapper()
    session_lock = SessionLockManager()

    async def handle_message(message: ISACMessage) -> None:
        """入口: 会话锁保证同一会话串行 (SPECIFICATION.md 2.5)。

        注意: 此时 message.session_id 尚未赋值，因此锁键使用 platform:user_id:group_id，
        避免退化为全局串行。
        """
        lock_key = f"{message.platform}:{message.user_id or 'unknown'}:{message.group_id or 'private'}"
        lock = await session_lock.acquire(lock_key)
        # CR3-Fix: acquire() 会累加 _waiters 引用计数, 必须配对 release() 才能触发
        # SessionLockManager 的 K7 锁回收; 此前主链路只 acquire 不 release, 导致
        # _locks/_waiters 按不同 platform:user:group 无界增长 (长期运行内存泄漏)。
        try:
            async with lock:
                await process_message(
                    message,
                    event_bus=event_bus,
                    router=router,
                    session_mgr=session_mgr,
                    user_mapper=user_mapper,
                    agent_manager=agent_manager,
                    channel_registry=channel_registry,
                    metrics=metrics,
                )
        finally:
            session_lock.release(lock_key)

    # 注入 Channel 适配器的消息回调
    for adapter in channel_registry.list():
        adapter.on_message = handle_message

    # ── Alert (规则驱动; 在 start 之前注册, 启动后才挂到 TaskGroup) ──
    alert_manager = AlertManager(metrics)
    for rule in get_default_alert_rules():
        alert_manager.add_rule(rule)

    # ── 启动编排 (K1): 所有资源通过 register_lifecycle 注册到 runtime ──
    # 启动顺序: Channel 适配器 → Control Plane (可选) → Alert → Provider 连接池关闭
    # 关闭顺序 (LIFO): Provider → Alert → Control → Channel
    runtime.register_lifecycle(
        "channels",
        channel_registry.start_all,
        channel_registry.stop_all,
    )
    control_config = global_config.get("control", {}) or {}
    if control_config.get("enabled"):
        # CR3: session_mgr/event_bus 此前经 services.get() 取值恒 None (键根本
        # 不存在), routes_sessions/routes_events 在生产从未挂载; 现在把 main()
        # 内已构造的真实实例直接传入。
        await _register_control_plane(
            runtime, control_config, agent_manager, router, bus, metrics,
            services.get("usage_store"), services.get("subagent_supervisor"),
            services.get("provider_manager"), services.get("model_catalog"),
            services.get("artifact_store"),
            session_mgr, services.get("metadata_store"),
            event_bus,
            services=services,
        )
    runtime.register_lifecycle(
        "alerts",
        alert_manager.start,
        alert_manager.stop,
    )
    # K2: Provider (httpx.AsyncClient 连接池) 在 shutdown 时 aclose, 避免连接泄漏;
    # 启动无需动作 (httpx.AsyncClient 惰性创建, 首次 chat 时才建池)。
    provider_manager = services["provider_manager"]
    runtime.register_lifecycle(
        "providers",
        _noop_start,
        provider_manager.aclose,
    )

    # K3: 先执行 storage schema init/migration (MetadataStore + VectorStore), 保证
    # 后续 load_persisted_agents 创建 Agent 时 warm_up_sparse_index 能从 SQLite 读数据;
    # 再注册到 runtime 的 LIFO 关闭链 (storage 关闭时无显式动作, aiosqlite 每次连接即关)。
    storage_start = services["storage_start"]
    await storage_start()
    runtime.register_lifecycle("storage", _noop_start, _noop_start)

    # J2: 制品存储生命周期 (启动 schema 初始化 + 周期 TTL 扫描; 关闭时 sweep 兜底)。
    # ArtifactStore 在 build_services 中无条件构造, 这里无条件注册: 即使无多模态
    # Provider 注册, start_ttl_sweep 也只是周期扫描空 DB, 开销可忽略。
    artifact_store = services["artifact_store"]
    runtime.register_lifecycle("artifact_store", artifact_store.start, artifact_store.stop)

    # J1: 用量存储生命周期 (仅启用计量时注册; stop 时先 flush 缓冲再关连接)。
    _register_usage_lifecycle(runtime, services)
    # J4: 子任务日志生命周期 (仅启用 subagent.enabled 时注册)。
    _register_subagent_lifecycle(runtime, services)

    # 先恢复持久化 Agent (data/agents/*/config.jsonc, enabled=true 的自动 start),
    # 再回退到默认 Agent 保证无任何持久化配置时也能跑通 (CODE_REVIEW_REPORT.md #2)。
    agents_dir = global_config.get("control", {}).get(
        "agents_dir", str(DATA_DIR / "agents")
    )
    restore_report = await load_persisted_agents(agent_manager, agents_dir)
    if restore_report:
        logger.info("持久化 Agent 恢复完成", report=restore_report)
    default_instance = await ensure_default_agent(agent_manager, global_config)
    # Q0: 裸部署无任何路由规则时, 已启用平台的消息兜底路由到默认 Agent (否则全 DROP)
    _ensure_default_routing(router, channel_registry, default_instance.agent_id)
    await event_bus.fire_async(EventType.ON_START, {"config": global_config})

    # ── 进入 runtime (启动 TaskGroup + 触发所有 register_lifecycle.start) ──
    await runtime.start()
    # J4-3: SubAgent 重启恢复 — 把 running/queued 标记为 cancelled (中断后不恢复旧进度)。
    # 必须在 runtime.start() 之后调用 (subagent_journal 已 start, DB 连接就绪)。
    await _restore_subagent_interrupts(services)
    logger.info("ISAC 启动完成")
    # Q0: try/finally 保证优雅关闭 —— Windows 上 add_signal_handler 注册失败,
    # Ctrl+C 以 KeyboardInterrupt/CancelledError 穿透 serve_forever, 此前会跳过
    # shutdown() 留下未释放的连接与后台任务; POSIX 信号路径 (serve_forever 正常
    # 返回) 行为不变。
    try:
        await runtime.serve_forever()
    finally:
        await runtime.shutdown()
        logger.info("ISAC 已退出")


async def _register_control_plane(
    runtime: ApplicationRuntime,
    control_config: dict[str, Any],
    agent_manager: AgentManager,
    router: MessageRouter,
    bus: InterAgentBus,
    metrics: MetricsCollector,
    usage_store: Any = None,
    subagent_supervisor: Any = None,
    provider_manager: Any = None,
    model_catalog: Any = None,
    artifact_store: Any = None,
    session_manager: Any = None,
    metadata_store: Any = None,
    event_bus: Any = None,
    *,
    services: dict[str, Any] | None = None,
) -> None:
    """把控制面 (uvicorn Server) 注册到 runtime 的生命周期管理。

    uvicorn Server 用 should_exit=True 触发优雅关闭, 再 await shutdown() 等连接退出;
    serve() 是长循环, 通过 runtime.spawn 挂到 TaskGroup 持有强引用
    (CODE_REVIEW_REPORT.md #12/#13)。
    """
    try:
        import uvicorn

        from isac.control.api.server import create_control_app
        from isac.control.defaults import enforce_safe_host
        from isac.plugin.runtime.manager import PluginManager

        # 用真实配置初始化 PluginManager, 并加载 plugins/ 目录下的全部插件。
        # 失败不阻塞控制面启动: 加载报告会作为日志输出, 单个插件加载错误由 PluginManager
        # 自身错误隔离 (CODE_REVIEW_REPORT.md #27)。
        plugin_config = (control_config.get("plugins", {}) or {}) if isinstance(control_config, dict) else {}
        plugin_manager = PluginManager(plugin_config)
        plugins_dir = Path(control_config.get("plugins_dir", "plugins"))
        # 用 to_thread 包装 Path.exists 避免 event loop 内 blocking IO (ruff ASYNC240)。
        if await asyncio.to_thread(plugins_dir.exists):
            try:
                load_report = await plugin_manager.load_all(plugins_dir)
                if load_report:
                    logger.info("插件加载完成", report=load_report)
                # CR3-H2: 接线 on_load 生命周期钩子 —— 此前 call_on_load 全仓无
                # 调用点, 插件即使被加载也是"惰性"的 (无法注册事件订阅/互联钩子/
                # Admin Route)。event_bus/inter_agent_bus/router 都是生产实例,
                # 插件经 on_event_intercept/on_event_async 的订阅会真实参与
                # process_message 主链路。tools/commands/prompt_builder 是
                # per-Agent 注册表, 留 None (插件调用对应 register_* 会得到明确
                # 报错并被 call_on_load 按插件隔离); per-Agent 桥接见 P 节点。
                await _fire_plugin_on_load(
                    plugin_manager, services or {}, event_bus=event_bus, bus=bus, router=router
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("插件加载过程异常, 不阻塞控制面", error=str(exc), exc_info=True)

        # CR3-L3: BM25 内存索引解析器 (namespace → SparseBM25Index), 让治理路由的
        # delete/restore/correct 能同步内存索引。
        sparse_indexes = (services or {}).get("sparse_indexes") or {}
        app = create_control_app(
            agent_manager,
            router,
            bus,
            plugin_manager,
            control_config,
            metrics=metrics,
            usage_store=usage_store,
            subagent_supervisor=subagent_supervisor,
            provider_manager=provider_manager,
            model_catalog=model_catalog,
            artifact_store=artifact_store,
            session_manager=session_manager,
            metadata_store=metadata_store,
            event_bus=event_bus,
            sparse_resolver=sparse_indexes.get,
        )
        host = enforce_safe_host(control_config.get("host", "127.0.0.1"))
        port = int(control_config.get("port", 8765))
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
        )
        server = uvicorn.Server(config)

        async def _start_control() -> None:
            # uvicorn.Server.serve 是阻塞循环, 通过 runtime.spawn 挂到 TaskGroup;
            # serve_forever 的 request_stop 设置 server.should_exit 让 serve 返回。
            runtime.spawn(server.serve(), name="control-plane-uvicorn")

        async def _stop_control() -> None:
            server.should_exit = True
            try:
                await asyncio.wait_for(server.shutdown(), timeout=5.0)
            except TimeoutError:
                logger.warning("控制面 5 秒未完成优雅关闭, 继续往下走")
            except Exception as exc:  # noqa: BLE001
                logger.warning("控制面关闭异常", error=str(exc))

        runtime.register_lifecycle("control_plane", _start_control, _stop_control)
        logger.info("控制面已注册", host=host, port=port)
    except Exception as exc:
        logger.error("控制面注册失败 (不阻塞数据面)", error=str(exc), exc_info=True)


async def _fire_plugin_on_load(
    plugin_manager: Any,
    services: dict[str, Any],
    *,
    event_bus: Any = None,
    bus: Any = None,
    router: Any = None,
) -> None:
    """CR3-H2: 构造 PluginContext 并触发全部 Native 插件的 on_load 钩子。

    agent_hooks 是进程级共享注册表 (services["plugin_agent_hooks"]), 组装每个
    Agent 时由 assemble_agent 合并进该 Agent 的私有 hooks; event_bus 缺失
    (极少数测试路径) 时跳过, 不构造无效 context。失败只记日志不阻塞启动。
    """
    if event_bus is None:
        logger.debug("event_bus 未注入, 跳过插件 on_load 接线")
        return
    try:
        from isac.agent.hooks import AgentHooks
        from isac.plugin.native.plugin import make_plugin_context

        plugin_agent_hooks = services.setdefault("plugin_agent_hooks", AgentHooks())
        context = make_plugin_context(
            agent_hooks=plugin_agent_hooks,
            event_bus=event_bus,
            services=services,
            inter_agent_bus=bus,
            router=router,
        )
        on_load_report = await plugin_manager.call_on_load(context)
        if on_load_report:
            logger.info("插件 on_load 完成", report=on_load_report)
    except Exception as exc:  # noqa: BLE001
        logger.warning("插件 on_load 接线失败, 不阻塞控制面", error=str(exc), exc_info=True)


def _register_usage_lifecycle(runtime: ApplicationRuntime, services: dict[str, Any]) -> None:
    """J1: 仅在启用计量时注册用量存储 + 周期性 flush 的生命周期。

    未启用计量 (usage_store 为 None) 时直接返回, 不注册任何生命周期, 主链路零变化。
    start: 先打开 DB 连接再启动周期任务 (避免周期任务第一次 tick 时连接还没就位);
    stop: 先停周期任务 (内部已含最终 flush) 再关连接, 顺序反过来会导致最后一批
    缓冲事件在落库前连接已关闭而丢失。
    """
    usage_store = services.get("usage_store")
    if usage_store is None:
        return
    usage_recorder = services.get("usage_recorder")

    async def _usage_start() -> None:
        await usage_store.start()
        if usage_recorder is not None:
            await usage_recorder.start()

    async def _usage_stop() -> None:
        if usage_recorder is not None:
            await usage_recorder.stop()
        await usage_store.stop()

    runtime.register_lifecycle("usage_store", _usage_start, _usage_stop)


def _register_subagent_lifecycle(runtime: ApplicationRuntime, services: dict[str, Any]) -> None:
    """J4: 仅在启用 subagent 日志时注册 Journal 生命周期。

    未启用 (subagent_journal 为 None) 时直接返回, 不创建任何 DB 文件。
    """
    journal = services.get("subagent_journal")
    if journal is None:
        return
    runtime.register_lifecycle("subagent_journal", journal.start, journal.stop)


async def _restore_subagent_interrupts(services: dict[str, Any]) -> None:
    """J4-3: SubAgent 重启恢复, 把 running/queued 标记为 cancelled。

    必须在 runtime.start() 之后调用 (subagent_journal 已 start, DB 连接就绪);
    journal 未启用或 supervisor 不存在时 no-op。
    """
    supervisor = services.get("subagent_supervisor")
    if supervisor is None:
        return
    try:
        marked = await supervisor.restore_interrupted()
        if marked > 0:
            logger.info("SubAgent 重启恢复: 已标记中断任务", marked=marked)
    except Exception as exc:  # noqa: BLE001
        logger.warning("SubAgent 重启恢复失败, 不阻塞启动", error=str(exc))


def _get_version() -> str:
    from isac import __version__

    return __version__


async def _load_persisted_links(bus: InterAgentBus, path: Path) -> None:
    """从 data/links.jsonc 恢复互联 Link (CODE_REVIEW_REPORT.md #3)。

    文件不存在或损坏时不阻塞启动; 损坏时仅记录 warning 并跳过, 让 in-memory 状态保持干净。
    """
    raw = await asyncio.to_thread(_read_links_file, path)
    if raw is None:
        return
    for item in raw.get("links", []) or []:
        try:
            bus.add_link(InterAgentLink(**item))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Link 恢复失败, 跳过该项", link=item, error=str(exc))


def _read_links_file(path: Path) -> dict | None:
    """同步读取并解析 links.jsonc; 不存在/损坏返回 None。

    拆成同步 helper 是为了让 async 调用方用 asyncio.to_thread 包装, 不在事件循环里
    直接执行 blocking IO (ruff ASYNC240)。
    """
    if not path.exists():
        return None
    try:
        try:
            import json5 as _json5

            return dict(_json5.loads(path.read_text(encoding="utf-8")))
        except ImportError:
            import json

            return dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001
        logger.warning("links.jsonc 解析失败, 跳过恢复", path=str(path), error=str(exc))
        return None
