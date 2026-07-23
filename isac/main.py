"""ISAC 应用入口: 组装所有组件 + 依赖注入 (DEVELOP.md 1.2)。

组装顺序遵循导入依赖链:
utils → provider → memory → persona → agent → gating → router
→ gateway → channel → commands → plugin → runtime → control
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from isac.channel.model import ISACMessage
from isac.channel.registry import ChannelRegistry
from isac.core.events import EventType
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
from isac.provider.llm.openai_compat import OpenAICompatProvider
from isac.provider.llm.stub import StubProvider
from isac.provider.manager import ProviderManager
from isac.router.router import MessageRouter
from isac.router.rules import load_rules
from isac.runtime.bus import InterAgentBus
from isac.runtime.manager import AgentManager, ensure_default_agent
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
) -> None:
    """消息主链路: EventBus → Router → Agent (DEVELOP.md 1.2 依赖注入)。"""
    payload = await event_bus.fire_intercept(EventType.ON_MESSAGE, message)
    if payload is None:
        return  # 被插件拦截
    message = payload

    decision = await router.route(message)
    if decision is None:
        return  # 路由无匹配 → DROP
    routed_message = dataclasses.replace(message, content=decision.content)

    session = await session_mgr.get_or_create(routed_message, agent_id=decision.agent_id)
    profile = await user_mapper.resolve(routed_message.platform, routed_message.user_id, routed_message.user_name)
    reply = await agent_manager.handle_message(decision.agent_id, routed_message, session, profile)
    if reply:
        await _send_reply(channel_registry, routed_message, reply, decision.agent_id)
    await event_bus.fire_async(EventType.POST_MESSAGE, routed_message)


async def _send_reply(
    channel_registry: ChannelRegistry,
    incoming: ISACMessage,
    reply_text: str,
    agent_id: str,
) -> None:
    """把 Agent 的文本回复经原 Channel 适配器发送。"""
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
        content=reply_text,
        reply_to=incoming.msg_id,
    )
    success = await adapter.send(reply)
    if not success:
        logger.warning("回复发送失败", platform=incoming.platform, agent_id=agent_id)
    else:
        logger.info("Agent 回复已发送", agent_id=agent_id, platform=incoming.platform, length=len(reply_text))


def register_llm_provider(provider_manager: ProviderManager, llm_config: dict[str, Any]) -> None:
    """按配置注册 LLM Provider。

    真实 provider+api_key 已配置但 OpenAICompatProvider 仍是未实现的桩时, 不再静默
    注册 StubProvider 冒充成功接入——注册真实的 OpenAICompatProvider, 它的 chat()
    会诚实地抛出 NotImplementedError, 经 chat_with_retry() 的兜底重试/降级逻辑
    (isac/provider/manager.py) 最终仍能拿到回复, 但每次调用都会留下 ERROR 日志,
    而不是像 Stub 一样悄无声息地表现正常 (CODE_REVIEW_REPORT.md #4)。仅在完全未配置
    任何 Provider 时才用 Stub 作为开发态兜底, 保证无 LLM 配置也能跑通主链路。

    范围说明: 不实现 OpenAICompatProvider 的真实 HTTP 调用 (独立后续 initiative)。
    """
    if llm_config.get("provider") and llm_config.get("api_key"):
        logger.critical(
            "已配置真实 LLM Provider, 但 OpenAICompatProvider 尚未实现真实调用; "
            "消息处理将收到降级回复而非真实模型输出, 请勿在生产环境依赖当前状态",
            provider=llm_config.get("provider"),
            model=llm_config.get("model", ""),
        )
        provider_manager.register(
            OpenAICompatProvider(
                api_key=str(llm_config.get("api_key", "")),
                base_url=str(llm_config.get("base_url", "")),
                model=str(llm_config.get("model", "")),
            )
        )
    else:
        provider_manager.register(StubProvider())


def build_services(global_config: dict[str, Any]) -> dict[str, Any]:
    """构建共享服务字典 (供 AgentManager 组装 AgentInstance)。"""
    provider_manager = ProviderManager(global_config.get("llm", {}))
    memory_config = global_config.get("memory", {})
    metadata_store: MetadataStore | None = None
    vector_store: VectorStore | None = None
    graph_store: GraphStore | None = None
    sparse_indexes: dict[str, SparseBM25Index] = {}
    embedder: EmbeddingManager | None = None
    reranker: Reranker | None = None

    if memory_config.get("enabled"):
        memory_dir = DATA_DIR / "memory"
        metadata_store = MetadataStore(str(memory_dir / "metadata.db"))
        vector_store = VectorStore(
            str(memory_dir / "vectors.db"),
            dimension=int(memory_config.get("embedding", {}).get("dimension", 1024) or 1024),
        )
        graph_store = GraphStore(str(memory_dir / "graph.db"))
        embedder = EmbeddingManager(memory_config.get("embedding", {}))
        reranker = Reranker(memory_config.get("reranker", {}))

    def memory_factory(namespace: str) -> Any:
        if not memory_config.get("enabled"):
            return NoOpMemoryPipeline(namespace)
        assert metadata_store is not None
        assert vector_store is not None
        assert graph_store is not None
        assert embedder is not None
        sparse = sparse_indexes.setdefault(namespace, SparseBM25Index())
        return MemoryRetrievalPipeline(
            namespace=namespace,
            metadata=metadata_store,
            vector=vector_store,
            sparse=sparse,
            graph=graph_store,
            embedder=embedder,
            reranker=reranker,
        )

    return {
        "global_config": global_config,
        "provider_manager": provider_manager,
        "memory_factory": memory_factory,
    }


async def main() -> None:
    """应用主入口。"""
    global_config = load_config(DATA_DIR / "config.jsonc")
    setup_logger(debug=bool(global_config.get("debug", False)))
    logger.info("ISAC 启动中", version=_get_version())

    # ── Provider ────────────────────────────────────────────
    services = build_services(global_config)
    register_llm_provider(services["provider_manager"], global_config.get("llm", {}))

    # ── Runtime (Agent 管理 + 互联总线) ─────────────────────
    agent_manager = AgentManager(services)
    bus = InterAgentBus()
    # TODO: bus.set_deliver(...) 投递到目标 Agent 的 Agent Loop

    # ── Router (Channel 与 Agent 解耦) ──────────────────────
    rules = load_rules(global_config.get("router", {}).get("rules_file", DATA_DIR / "routing.jsonc"))
    router = MessageRouter(rules, agents_provider=agent_manager.routing_infos)

    # ── Channel ─────────────────────────────────────────────
    channel_registry = ChannelRegistry()
    onebot_config = global_config.get("channels", {}).get("onebot")
    if onebot_config and onebot_config.get("enabled"):
        # 惰性导入 OneBot 适配器，避免 aiocqhttp 成为强制依赖
        from isac.channel.adapters.onebot.adapter import OneBotAdapter

        onebot_adapter = OneBotAdapter(onebot_config)
        channel_registry.register(onebot_adapter)

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
        async with lock:
            await process_message(
                message,
                event_bus=event_bus,
                router=router,
                session_mgr=session_mgr,
                user_mapper=user_mapper,
                agent_manager=agent_manager,
                channel_registry=channel_registry,
            )

    # 注入 Channel 适配器的消息回调
    for adapter in channel_registry.list():
        adapter.on_message = handle_message

    # ── Control Plane (可选) ─────────────────────────────────
    control_config = global_config.get("control", {})
    if control_config.get("enabled"):
        await _start_control_plane(control_config, agent_manager, router, bus)

    # ── 启动 ────────────────────────────────────────────────
    await ensure_default_agent(agent_manager, global_config)
    await event_bus.fire_async(EventType.ON_START, {"config": global_config})
    logger.info("ISAC 启动完成")
    await channel_registry.start_all()


async def _start_control_plane(
    control_config: dict[str, Any],
    agent_manager: AgentManager,
    router: MessageRouter,
    bus: InterAgentBus,
) -> None:
    """启动控制面 (Admin API)。失败不阻塞数据面 (DEVELOP.md 7.4)。"""
    try:
        import uvicorn

        from isac.control.api.server import create_control_app
        from isac.control.defaults import enforce_safe_host
        from isac.plugin.runtime.manager import PluginManager

        app = create_control_app(agent_manager, router, bus, PluginManager({}), control_config)
        host = enforce_safe_host(control_config.get("host", "127.0.0.1"))
        port = int(control_config.get("port", 8765))
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
        )
        import asyncio

        asyncio.get_running_loop().create_task(uvicorn.Server(config).serve())
        logger.info("控制面已启动", host=host, port=port)
    except Exception as exc:
        logger.error("控制面启动失败 (不阻塞数据面)", error=str(exc), exc_info=True)


def _get_version() -> str:
    from isac import __version__

    return __version__
