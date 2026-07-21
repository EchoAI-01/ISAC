"""ISAC 应用入口: 组装所有组件 + 依赖注入 (DEVELOP.md 1.2)。

组装顺序遵循导入依赖链:
utils → provider → memory → persona → agent → gating → router
→ gateway → channel → commands → plugin → runtime → control

TODO(Day 9): data/config.jsonc 端到端联调 (QQ 消息 → LLM → 回复)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from isac.channel.model import ISACMessage
from isac.channel.registry import ChannelRegistry
from isac.core.events import EventType
from isac.gateway.event_bus import EventBus
from isac.gateway.lock import SessionLockManager
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.memory.pipeline import NoOpMemoryPipeline
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


def build_services(global_config: dict[str, Any]) -> dict[str, Any]:
    """构建共享服务字典 (供 AgentManager 组装 AgentInstance)。

    TODO(Day 19-22): memory_factory 返回真实 MemoryRetrievalPipeline
    (MetadataStore + VectorStore + SparseBM25Index + GraphStore + EmbeddingManager)。
    """
    provider_manager = ProviderManager(global_config.get("llm", {}))

    def memory_factory(namespace: str) -> Any:
        # TODO(D5-D7): 替换为真实 MemoryRetrievalPipeline
        # 当前使用 NoOp 实现，保证主链路可启动，记忆注入器返回空字符串
        return NoOpMemoryPipeline(namespace)

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
    # TODO(D8): 当配置合法时注册 OpenAICompatProvider，否则使用 StubProvider 保证可启动
    provider_manager = services["provider_manager"]
    llm_config = global_config.get("llm", {})
    if llm_config.get("provider") and llm_config.get("api_key"):
        # TODO(D8): 注册 OpenAICompatProvider
        provider_manager.register(StubProvider())
    else:
        provider_manager.register(StubProvider())

    # ── Runtime (Agent 管理 + 互联总线) ─────────────────────
    agent_manager = AgentManager(services)
    bus = InterAgentBus()
    # TODO(Day 41): bus.set_deliver(...) 投递到目标 Agent 的 Agent Loop

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
            await process_message(message)

    async def process_message(message: ISACMessage) -> None:
        """消息主链路: EventBus → Router → Agent (DEVELOP.md 1.2 依赖注入)。"""
        payload = await event_bus.fire_intercept(EventType.ON_MESSAGE, message)
        if payload is None:
            return  # 被插件拦截

        decision = await router.route(message)
        if decision is None:
            return  # 路由无匹配 → DROP

        session = await session_mgr.get_or_create(message, agent_id=decision.agent_id)
        profile = await user_mapper.resolve(message.platform, message.user_id, message.user_name)
        reply = await agent_manager.handle_message(decision.agent_id, message, session, profile)
        if reply:
            await _send_reply(channel_registry, message, reply, decision.agent_id)
        await event_bus.fire_async(EventType.POST_MESSAGE, message)

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
        from isac.plugin.runtime.manager import PluginManager

        app = create_control_app(agent_manager, router, bus, PluginManager({}), control_config)
        config = uvicorn.Config(
            app,
            host=control_config.get("host", "127.0.0.1"),
            port=int(control_config.get("port", 8765)),
            log_level="warning",
        )
        import asyncio

        asyncio.get_running_loop().create_task(uvicorn.Server(config).serve())
        logger.info("控制面已启动", host=control_config.get("host"), port=control_config.get("port"))
    except Exception as exc:
        logger.error("控制面启动失败 (不阻塞数据面)", error=str(exc), exc_info=True)


def _get_version() -> str:
    from isac import __version__

    return __version__
