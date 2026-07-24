"""ISAC 应用入口: 组装所有组件 + 依赖注入 (DEVELOP.md 1.2)。

组装顺序遵循导入依赖链:
utils → provider → memory → persona → agent → gating → router
→ gateway → channel → commands → plugin → runtime → control
"""

from __future__ import annotations

import asyncio
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
from isac.observability import AlertManager, MetricsCollector, get_default_alert_rules, get_default_metrics
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

    session = await session_mgr.get_or_create(routed_message, agent_id=decision.agent_id)
    profile = await user_mapper.resolve(routed_message.platform, routed_message.user_id, routed_message.user_name)
    try:
        reply = await agent_manager.handle_message(decision.agent_id, routed_message, session, profile)
    except Exception:
        metrics.counter("isac_messages_failed_total").inc()
        raise
    metrics.counter("isac_messages_processed_total").inc()
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


def build_services(global_config: dict[str, Any]) -> dict[str, Any]:
    """构建共享服务字典 (供 AgentManager 组装 AgentInstance)。

    metrics 是应用生命周期内唯一的 MetricsCollector 实例, 通过这个 services 字典
    注入给 AgentManager/ISACAgentLoop (二者已持有 services), 并显式传给 ProviderManager/
    MemoryRetrievalPipeline (CODE_REVIEW_REPORT.md #5)。
    """
    metrics = get_default_metrics()
    provider_manager = ProviderManager(global_config.get("llm", {}), metrics=metrics)
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
            metrics=metrics,
        )

    return {
        "global_config": global_config,
        "provider_manager": provider_manager,
        "memory_factory": memory_factory,
        "metrics": metrics,
    }


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
    setup_logger(debug=bool(global_config.get("debug", False)))
    logger.info("ISAC 启动中", version=_get_version())

    runtime = ApplicationRuntime()
    runtime.install_signal_handlers()

    # ── Provider ────────────────────────────────────────────
    services = build_services(global_config)
    metrics: MetricsCollector = services["metrics"]
    register_llm_provider(services["provider_manager"], global_config.get("llm", {}))

    # ── Runtime (Agent 管理 + 互联总线) ─────────────────────
    agent_manager = AgentManager(services)
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
                metrics=metrics,
            )

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
        await _register_control_plane(
            runtime, control_config, agent_manager, router, bus, metrics
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

    # 先恢复持久化 Agent (data/agents/*/config.jsonc, enabled=true 的自动 start),
    # 再回退到默认 Agent 保证无任何持久化配置时也能跑通 (CODE_REVIEW_REPORT.md #2)。
    agents_dir = global_config.get("control", {}).get(
        "agents_dir", str(DATA_DIR / "agents")
    )
    restore_report = await load_persisted_agents(agent_manager, agents_dir)
    if restore_report:
        logger.info("持久化 Agent 恢复完成", report=restore_report)
    await ensure_default_agent(agent_manager, global_config)
    await event_bus.fire_async(EventType.ON_START, {"config": global_config})

    # ── 进入 runtime (启动 TaskGroup + 触发所有 register_lifecycle.start) ──
    await runtime.start()
    logger.info("ISAC 启动完成")
    await runtime.serve_forever()
    await runtime.shutdown()
    logger.info("ISAC 已退出")


async def _register_control_plane(
    runtime: ApplicationRuntime,
    control_config: dict[str, Any],
    agent_manager: AgentManager,
    router: MessageRouter,
    bus: InterAgentBus,
    metrics: MetricsCollector,
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
            except Exception as exc:  # noqa: BLE001
                logger.warning("插件加载过程异常, 不阻塞控制面", error=str(exc), exc_info=True)

        app = create_control_app(
            agent_manager,
            router,
            bus,
            plugin_manager,
            control_config,
            metrics=metrics,
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
