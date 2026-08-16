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
from isac.core.constants import INTERAGENT_PLATFORM
from isac.core.events import EventType
from isac.core.policy import EnableMatrix
from isac.core.types import ProgressEvent
from isac.gateway.event_bus import EventBus
from isac.gateway.identity.resolver import IdentityResolver
from isac.gateway.incoming_media import download_inbound_media
from isac.gateway.lock import SessionLockManager
from isac.gateway.models import UserProfile
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
from isac.utils.security import SecretStore, resolve_secrets_in_config

logger = get_logger(__name__)

DATA_DIR = Path("data")

# T2: 首启自动创建的 data/ 子目录 (被 build_services 各组件引用的路径)。
# 集中创建 + 各组件既有惰性 mkdir 双保险; 这里只建目录占位, 不创建文件, 零行为变化。
_DATA_SUBDIRS: tuple[str, ...] = (
    "agents",
    "memory",
    "gateway",
    "artifacts",
    "subagent",
    "usage",
    "workflows",
)


def _ensure_data_dirs() -> None:
    """T2: 首启自动创建 data/ 及被引用子目录。

    此前各组件惰性自建 (path.parent.mkdir), 无统一入口; 集中创建让首启目录结构透明、
    日志可观测。已存在目录 exist_ok=True 零冲突; 不创建文件, 不触碰既有数据。
    """
    for sub in _DATA_SUBDIRS:
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)


async def _resolve_identity(
    profile: UserProfile,
    identity_resolver: IdentityResolver | None,
    message: ISACMessage,
) -> None:
    """S4: 身份归一锚点 —— 命中归一 person_id 时就地覆盖 profile.user_id。

    identity.enabled 时把 (platform, user_id) 归一到统一 person_id, 使下游记忆读写
    (以 profile.user_id 为主键) 按归一身份聚合。identity_resolver=None (默认关闭) 时
    直接返回, 零行为变化; 无 verified/启发式绑定时 resolver 兜底委托同一 user_mapper,
    person_id 不变 = 无副作用; resolver 抛异常时降级用基础画像 (不冒泡到主链路)。
    """
    if identity_resolver is None:
        return
    try:
        person_id = await identity_resolver.resolve(message.platform, message.user_id, message.user_name)
        if person_id:
            profile.user_id = person_id
    except Exception:  # noqa: BLE001
        logger.warning("身份归一失败, 降级用基础画像", platform=message.platform, exc_info=True)


def _build_identity_resolver(
    global_config: dict[str, Any], user_mapper: UserMapper
) -> IdentityResolver | None:
    """S4: 按 identity.enabled 构造跨平台身份归一器 (默认关闭 → None → 主链路零行为变化)。

    启用时组合同一 user_mapper (不改动它), 只把 verified/启发式绑定命中的归一 person_id
    覆盖到 profile.user_id; heuristic_enabled 默认 False 防误合并。
    """
    identity_config = global_config.get("identity", {}) or {}
    if not identity_config.get("enabled"):
        return None
    return IdentityResolver(
        user_mapper,
        heuristic_enabled=bool(identity_config.get("heuristic_enabled", False)),
        db_path=str(DATA_DIR / "gateway" / "person_identities.db"),
    )


async def process_message(
    message: ISACMessage,
    *,
    event_bus: EventBus,
    router: MessageRouter,
    session_mgr: SessionManager,
    user_mapper: UserMapper,
    agent_manager: AgentManager,
    channel_registry: ChannelRegistry,
    identity_resolver: IdentityResolver | None = None,
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

    # R1-②: 入站媒体下载落盘 (扫 routed_message.segments 的 image/voice/video/file,
    # HTTP 下载为 bytes → uploads_store.put → 回填 media_uri 供工具经 MediaNormalizer 读)。
    # uploads_store 为 None (未启用) 或无 media segment 时直接跳过, 零行为变化。
    uploads_store = getattr(agent_manager, "_services", {}).get("uploads_store")
    if uploads_store is not None:
        try:
            await download_inbound_media(routed_message, uploads_store)
        except Exception as exc:  # noqa: BLE001 入站下载失败不阻塞消息主链路
            logger.warning("入站媒体下载落盘异常, 继续", error=str(exc))

    # Q0: 在 get_or_create 改写 session_id 为内部 sess_* 之前, 捕获适配器侧的
    # 平台会话键 (如 WebChat 客户端自带的 session_id)。出站回复/进度帧必须用
    # 平台键路由, 否则 WebChat 队列键与客户端轮询键对不上, 回复永远取不到。
    platform_session_id = routed_message.session_id
    session = await session_mgr.get_or_create(routed_message, agent_id=decision.agent_id)
    # P1: 平台会话键落到 Session, 出站主动消息 (强制话轮) 才能路由回正确队列
    if platform_session_id and not session.platform_session_id:
        session.platform_session_id = platform_session_id
    profile = await user_mapper.resolve(routed_message.platform, routed_message.user_id, routed_message.user_name)
    # S4: 身份归一锚点 (identity_resolver=None 时零行为变化, 见 _resolve_identity)。
    await _resolve_identity(profile, identity_resolver, routed_message)

    # P2 Mesh: 候选仲裁 (可能改写归属 Agent) + observer 旁听 (只入记忆不回复)。
    # 无 Agent 配置 mesh_role 时整段短路 = 单主路由, 零行为变化。
    final_agent_id = await _apply_mesh_routing(
        decision, routed_message, session, profile, session_mgr, agent_manager
    )
    if final_agent_id != decision.agent_id:
        # 仲裁换了回复者: 会话按新 Agent 重新解析 (Session 含 agent_id 维度)
        session = await session_mgr.get_or_create(routed_message, agent_id=final_agent_id)
        if platform_session_id and not session.platform_session_id:
            session.platform_session_id = platform_session_id

    progress_sender = _make_progress_sender(
        channel_registry, routed_message, final_agent_id, platform_session_id
    )
    try:
        reply = await agent_manager.handle_message(
            final_agent_id, routed_message, session, profile, progress_sender=progress_sender
        )
    except Exception:
        metrics.counter("isac_messages_failed_total").inc()
        raise
    metrics.counter("isac_messages_processed_total").inc()
    if reply:
        # R1-①: 取目标 Agent 的 artifact_store 供 _send_reply 扫回复 artifact 转 segment
        await _send_reply(
            channel_registry, routed_message, reply, final_agent_id, platform_session_id,
            artifact_store=await _resolve_artifact_store(agent_manager, final_agent_id),
        )
    await event_bus.fire_async(EventType.POST_MESSAGE, routed_message)


async def _resolve_artifact_store(agent_manager: Any, agent_id: str) -> Any:
    """R1-①: 从 agent_manager 取目标 Agent 的 artifact_store (无 get/instance None 时 None)。"""
    _get = getattr(agent_manager, "get", None)
    if not callable(_get):
        return None
    try:
        instance = await _get(agent_id)
        return (instance.services or {}).get("artifact_store") if instance else None
    except Exception:  # noqa: BLE001
        return None


async def _apply_mesh_routing(
    decision: Any,
    message: ISACMessage,
    session: Any,
    profile: Any,
    session_mgr: SessionManager,
    agent_manager: AgentManager,
) -> str:
    """P2: observer 旁听 + candidate 仲裁, 返回最终处理该消息的 agent_id。

    - 无 Agent 配置 mesh_role → 直接返回 decision.agent_id (零行为变化)
    - observer: 各自用**自己的会话**旁听入记忆 (不回复, 与主处理并发执行)
    - candidate: 按 ReplyNecessityJudge 评分与 primary 比较, 显著更高 (>SWITCH_MARGIN)
      才切换回复者, 避免噪声抖动 (MeshRouter.arbitrate)
    """
    # getattr 防御: 旧测试替身/未升级的自定义 manager 无 mesh_roles → 单主路由
    roles_fn = getattr(agent_manager, "mesh_roles", None)
    roles = roles_fn() if roles_fn is not None else {}
    if not roles:
        return decision.agent_id
    from isac.runtime.mesh.router import MeshRouter

    mesh_decision = MeshRouter(agent_roles=roles).to_mesh_decision(decision)
    # observer 旁听: 后台并发写各自记忆, 不阻塞 primary 回复 (R2-3)。get_or_create
    # 是内存操作可直接 await; 真正耗时的 observe_message (store_episode 可能含
    # embedding 调用) 派生为后台任务, 由 AgentManager._memory_tasks 承接并在优雅
    # 关闭时 drain。
    for observer_id in mesh_decision.observer_agent_ids:
        observer_session = await session_mgr.get_or_create(message, agent_id=observer_id)
        agent_manager.schedule_observe_message(observer_id, message, observer_session, profile)
    if not mesh_decision.candidate_agent_ids:
        return decision.agent_id
    # 候选仲裁: primary 与各候选各自评分 (纯启发式, 不调 LLM)
    scores: dict[str, float] = {
        decision.agent_id: await agent_manager.gating_score(decision.agent_id, message, session, profile)
    }
    for candidate_id in mesh_decision.candidate_agent_ids:
        candidate_session = await session_mgr.get_or_create(message, agent_id=candidate_id)
        scores[candidate_id] = await agent_manager.gating_score(
            candidate_id, message, candidate_session, profile
        )
    winner = MeshRouter(agent_roles=roles).arbitrate(mesh_decision, gating_scores=scores)
    if winner and winner != decision.agent_id:
        logger.info(
            "Mesh 仲裁改写回复者", primary=decision.agent_id, winner=winner, reason=mesh_decision.reason
        )
    return winner or decision.agent_id


async def _send_reply(
    channel_registry: ChannelRegistry,
    incoming: ISACMessage,
    reply_text: str,
    agent_id: str,
    platform_session_id: str = "",
    *,
    artifact_store: Any = None,
) -> None:
    """把 Agent 的文本回复经原 Channel 适配器发送。

    Q0: platform_session_id 是 gateway 改写前的适配器侧会话键 (WebChat 客户端
    的 session_id); 出站按平台键路由, 客户端才能按自己的键轮询到回复。适配器
    未提供平台键时 (OneBot 等按 group/user 路由的平台) 回退内部 session_id。
    R1-①: 扫描回复文本中的 ``artifact:<64位hex>`` 引用, 经 ArtifactStore.get_ref
    取元数据 + MediaResolver.resolve_for_channel 转 Channel segment append 到
    reply.segments (此前只发文本, 生成的图/语音发不出去)。MediaResolver 不支持的
    平台 (webchat/telegram/discord) 跳过 segment, 仅文本。
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
    # R1-①: 扫 artifact 引用转 segment (artifact_store 注入时)
    if artifact_store is not None:
        await _append_artifact_segments(reply, artifact_store, incoming.platform)
    success = await adapter.send(reply)
    if not success:
        logger.warning("回复发送失败", platform=incoming.platform, agent_id=agent_id)
    else:
        logger.info("Agent 回复已发送", agent_id=agent_id, platform=incoming.platform, length=len(reply_text))


async def _append_artifact_segments(reply: ISACMessage, artifact_store: Any, platform: str) -> None:
    """R1-①: 扫回复文本 artifact:<hex> → get_ref → MediaResolver 转 segment。

    逐引用异常隔离 (单个 artifact 解析失败不影响其余)。segment append 到 reply.segments。
    """
    import re

    from isac.channel.media_resolver import MediaResolver

    ids = re.findall(r"artifact:([a-f0-9]{64})", reply.content or "")
    seen: set[str] = set()
    for aid in ids:
        if aid in seen:
            continue
        seen.add(aid)
        try:
            ref = await artifact_store.get_ref(aid)
            if ref is None:
                continue
            segment = MediaResolver.resolve_for_channel(platform, ref)
            if segment is not None:
                reply.segments.append(segment)
        except Exception as exc:  # noqa: BLE001
            logger.warning("artifact 转 segment 失败, 跳过", artifact_id=aid, error=str(exc))


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


def make_message_dispatcher(
    *,
    event_bus: EventBus,
    router: MessageRouter,
    session_mgr: SessionManager,
    user_mapper: UserMapper,
    agent_manager: AgentManager,
    channel_registry: ChannelRegistry,
    metrics: MetricsCollector,
    session_lock: SessionLockManager,
    identity_resolver: IdentityResolver | None = None,
    drain_timeout_seconds: float = 30.0,
) -> tuple[Callable[[ISACMessage], Awaitable[None]], Callable[[], Awaitable[None]]]:
    """P0: 构造并发消息分发器, 返回 (handle_message, drain_inflight)。

    此前 handle_message 同步 await 整条处理链 (门控→LLM→工具→回复), 适配器的
    收取循环被单条消息阻塞 —— 跨会话并行度完全取决于 Channel 库自身调度
    (Telegram/Discord/WebChat 的轮询循环整体串行)。现在:
    - handle_message 派生 asyncio.Task 后立即返回, 不同会话真并行;
    - 单会话串行保持: 锁键 platform:user:group (消息 session_id 尚未赋值),
      同会话任务按到达顺序创建, asyncio FIFO 就绪队列 + 公平锁保证按序获取;
    - 任务持强引用 (inflight 集合 + done 自清理), 异常在任务内捕获记日志,
      不产生 "Task exception was never retrieved";
    - drain_inflight 供优雅关闭调用: 停止收取后等待在途任务完成 (带超时),
      保证 shutdown 不丢已接收的消息。
    """
    inflight: set[asyncio.Task[None]] = set()

    async def _process_locked(message: ISACMessage) -> None:
        # P1: 锁外拟人化信号 —— 会话锁被正在 thinking 的上一条消息持有时, 新消息
        # 的缓存/唤醒/打断信号必须先于锁到达 ConversationRuntime (conversation
        # 关闭时 notify_incoming 内部短路, 零行为变化)。路由与会话解析幂等,
        # process_message 会再次执行 (代价可忽略)。get_or_create 会把
        # message.session_id 改写为内部 sess_*, 信号阶段结束后还原为平台会话键,
        # 保证 process_message 自己的 platform_session_id 捕获不受影响。
        platform_session_id = message.session_id
        try:
            decision = await router.route(message)
            if decision is not None:
                session = await session_mgr.get_or_create(message, agent_id=decision.agent_id)
                if platform_session_id and not session.platform_session_id:
                    session.platform_session_id = platform_session_id
                await agent_manager.notify_incoming(decision.agent_id, session.session_id, message)
        except Exception:  # noqa: BLE001
            logger.warning("锁外拟人化信号处理失败, 不影响主处理", exc_info=True)
        finally:
            message.session_id = platform_session_id
        lock_key = f"{message.platform}:{message.user_id or 'unknown'}:{message.group_id or 'private'}"
        lock = await session_lock.acquire(lock_key)
        # CR3-Fix: acquire() 会累加 _waiters 引用计数, 必须配对 release() 才能触发
        # SessionLockManager 的 K7 锁回收 (否则 _locks/_waiters 无界增长)。
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
                    identity_resolver=identity_resolver,
                    metrics=metrics,
                )
        except Exception:
            # 任务化后异常不再冒泡到适配器循环, 必须就地捕获记录
            logger.error(
                "消息处理任务异常", platform=message.platform, msg_id=message.msg_id, exc_info=True
            )
        finally:
            session_lock.release(lock_key)

    async def handle_message(message: ISACMessage) -> None:
        task = asyncio.create_task(
            _process_locked(message),
            name=f"msg-{message.platform}-{message.msg_id or 'anon'}",
        )
        inflight.add(task)
        task.add_done_callback(inflight.discard)

    async def drain_inflight() -> None:
        pending = [t for t in inflight if not t.done()]
        if not pending:
            return
        logger.info("等待在途消息处理完成", count=len(pending))
        _done, still_pending = await asyncio.wait(pending, timeout=drain_timeout_seconds)
        if still_pending:
            logger.warning("在途消息处理未在超时内完成, 继续关闭", count=len(still_pending))

    return handle_message, drain_inflight


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
    # O4 适配器: 飞书/企业微信已激活真实 Webhook + 出站消息; 公众号 (wechat mode="mp") 仍骨架。
    # 仅在显式 enabled 时注册, 默认不接入 → 零行为变化。
    feishu_config = channels_config.get("feishu")
    if feishu_config and feishu_config.get("enabled"):
        from isac.channel.adapters.feishu.adapter import FeishuAdapter

        channel_registry.register(FeishuAdapter(feishu_config))
    wechat_config = channels_config.get("wechat")
    if wechat_config and wechat_config.get("enabled"):
        from isac.channel.adapters.wechat.adapter import WeChatAdapter

        channel_registry.register(WeChatAdapter(wechat_config))
    qq_official_config = channels_config.get("qq_official")
    if qq_official_config and qq_official_config.get("enabled"):
        from isac.channel.adapters.qq_official.adapter import QQOfficialAdapter

        channel_registry.register(QQOfficialAdapter(qq_official_config))
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
        logger.warning(
            "未配置有效 LLM api_key (为空或占位符), 使用 Stub 回复; "
            "请在 data/config.jsonc 的 llm 段填入真实 api_key 后重启",
            provider=llm_config.get("provider"),
            api_key_placeholder=is_placeholder_key(api_key),
        )


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


def _build_tenant_manager(tenancy_config: dict[str, Any]) -> Any:
    """R6-①: tenancy.enabled 时构造 TenantManager (SQLite); 否则 None (路由不挂载, 零行为变化)。"""
    if not bool(tenancy_config.get("enabled")):
        return None
    from isac.runtime.tenancy.manager import TenantManager

    return TenantManager(db_path=str(DATA_DIR / "gateway" / "tenants.db"))


def _build_media_normalizer(global_config: dict[str, Any]) -> Any:
    """R1-②: 构造 MediaNormalizer, 白名单含 data/uploads (入站媒体下载落盘目录)。

    安全: transcribe_audio/understand_image 等工具必须先经 MediaNormalizer 校验
    media_uri (白名单 + MIME + 大小上限), 不能直接信任 LLM 工具参数里的任意路径。
    """
    from isac.utils.media import MediaNormalizer

    mn_config = dict(global_config.get("media_normalizer") or {})
    allowed = list(mn_config.get("allowed_dirs") or ["data/artifacts", "data/uploads"])
    if "data/uploads" not in allowed:
        allowed.append("data/uploads")
    mn_config["allowed_dirs"] = allowed
    return MediaNormalizer(mn_config)


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
    # R6-①: TenantManager (租户 CRUD + 成员, SQLite)。抽 helper 降 build_services 复杂度。
    # tenancy.enabled 时构造并传入控制面 routes_tenants; 默认关闭 → None → 路由不挂载。
    tenant_manager = _build_tenant_manager(tenancy_config)

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
    # R1-④: 加载价目表 (provider/model/modality → 价格快照); 文件不存在用空 catalog,
    # estimated_cost 恒 None (向后兼容)。与 ③ record_* 传的 provider/model 对齐闭环。
    pricing = PricingCatalog.load(DATA_DIR / "pricing.jsonc")
    usage_recorder = UsageRecorder(
        store=usage_store,
        pricing=pricing,
        flush_interval_seconds=float(usage_config.get("flush_interval_seconds", 30)),
    )
    return usage_store, usage_recorder


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


async def _answer_memory_query(
    agent_manager: AgentManager, target_agent_id: str, message: InterAgentMessage
) -> str:
    """P2: 接收端执行授权记忆查询, 返回格式化结果 (经 bus response 回到查询方)。

    scope 语义 (ROUTING_AND_AGENT_MESH.md §6.1): "user:<id>" / "group:<id>" ——
    复用 pipeline.search 的 user/group ACL 参数做真实裁剪; 未知格式保守跳过
    (绝不扩大可见范围)。检索失败返回空串 (查询方看到"无相关内容")。

    MVP-Fix (安全): **scopes 为空一律拒绝**。此前空 scopes 走无 user/group 参数
    的全量检索, 而 visible_memory_scopes 的默认值就是空 —— 管理员只授予
    permissions=["memory_query"] 却忘了配 scopes 时, 对端可读取目标 Agent 的
    全部记忆 (含其他用户的私聊), 违背 Link ACL 的 deny-by-default 语义。
    """
    instance = await agent_manager.get(target_agent_id)
    if instance is None or instance.status != "running":
        return ""
    filters = message.context.get("filters") or {}
    scopes = [str(s) for s in (filters.get("scopes") or []) if s]
    if not scopes:
        logger.warning(
            "跨 Agent 记忆查询被拒: Link 未配置 visible_memory_scopes (空 = 拒绝, 非全量)",
            from_agent=message.from_agent,
            target=target_agent_id,
        )
        return ""
    query = message.content
    hits: list[Any] = []
    try:
        for scope in scopes[:5]:
            kind, _, ident = scope.partition(":")
            if kind == "user" and ident:
                hits.extend(await instance.memory.search(query, top_k=3, user_id=ident))
            elif kind == "group" and ident:
                hits.extend(await instance.memory.search(query, top_k=3, group_id=ident))
            else:
                logger.warning("忽略无法识别的记忆可见范围 (保守跳过)", scope=scope)
    except Exception:  # noqa: BLE001
        logger.warning("跨 Agent 记忆查询失败", target=target_agent_id, exc_info=True)
        return ""
    seen: set[str] = set()
    lines: list[str] = []
    for hit in hits:
        if hit.id in seen:
            continue
        seen.add(hit.id)
        lines.append(f"- {hit.content[:200]}")
    return "\n".join(lines[:5])


async def _shutdown_message_pipeline(
    channel_registry: ChannelRegistry,
    drain_inflight: Callable[[], Awaitable[None]],
    agent_manager: AgentManager,
) -> None:
    """优雅关闭消息面: 停收取 → drain 在途消息 → drain 后台记忆 → 停主动调度。

    顺序要紧: 先停适配器不再收新消息, 再等在途任务落地, 最后停调度循环 —— 之后
    LIFO 才会去关 journal/usage/providers 等下游资源。
    MVP-Fix (两处):
    - 消息任务产出回复即离开 inflight, 其派生的**记忆写入**仍在跑, 此前不被
      等待 → 最后若干轮的 episodic/画像/快照在事件循环收尾取消任务时静默丢失。
    - ProactiveScheduler 的循环是裸 create_task (不在 runtime TaskGroup 里),
      此前无人停 → 关闭窗口内还会对已停适配器发起强制话轮。
    """
    await channel_registry.stop_all()
    await drain_inflight()
    await agent_manager.drain_background_tasks()
    for instance in await agent_manager.list():
        scheduler = instance.services.get("proactive_scheduler")
        if scheduler is not None:
            await scheduler.stop()
        # R3: 断开该 Agent 的 MCPClient (子进程/HTTP 连接), 避免关闭时泄漏。
        await agent_manager._disconnect_mcp_clients(instance)  # noqa: SLF001


async def _noop_start() -> None:
    """无启动动作的资源 (如 Provider 连接池: 惰性创建, 无需 start) 占位。"""
    return None


def _build_plugin_enable_matrix(services: dict[str, Any] | None) -> EnableMatrix:
    """Q3: 从 global_config 构造 PluginManager 的 EnableMatrix (Agent ∩ Channel ∩ 全局)。

    从 shared services 的 global_config 读取 policy 与 channels.matrix, 构造全局
    EnableMatrix。未注入 global_config 时返回空矩阵 (默认放行, 向后兼容)。
    """
    global_cfg = services.get("global_config") if isinstance(services, dict) else None
    if not isinstance(global_cfg, dict):
        return EnableMatrix()
    channel_overrides: dict[str, dict] = {}
    for platform, platform_cfg in (global_cfg.get("channels", {}) or {}).items():
        if isinstance(platform_cfg, dict) and "matrix" in platform_cfg:
            channel_overrides[platform] = platform_cfg["matrix"]
    return EnableMatrix(
        global_policy=global_cfg.get("policy", {}) or {},
        channel_overrides=channel_overrides,
    )


async def _close_storage_stores(services: dict[str, Any]) -> None:
    """C1: shutdown 时关闭 VectorStore/GraphStore 持久连接, 防 WAL/SHM 残留 + FD 泄漏。

    此前 storage lifecycle 的 stop 是 _noop_start, 持久连接在进程退出前不显式 close,
    嵌入启用时长期运行会让 vectors-<ns>.db 的 WAL/SHM 文件残留 + aiosqlite FD 泄漏。
    """
    vs_dict = services.get("vector_stores") or {}
    for ns, store in vs_dict.items():
        close = getattr(store, "close", None)
        if callable(close):
            try:
                await close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("VectorStore close 失败, 已忽略", namespace=ns, error=str(exc))
    gs = services.get("graph_store")
    if gs is not None:
        close = getattr(gs, "close", None)
        if callable(close):
            try:
                await close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("GraphStore close 失败, 已忽略", error=str(exc))


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
    # T2: 首启自动创建 data/ 及被引用子目录。此前各组件惰性自建 (path.parent.mkdir),
    # 但无统一入口, 首启日志零反馈、目录结构不透明。集中创建双保险 (各组件既有惰性
    # mkdir 保留, 零冲突)。
    _ensure_data_dirs()
    # R5: 密钥安全。配置中 api_key 形如 "secret:<key>" 时经 SecretStore 解密 (AES-256-GCM,
    # env ISAC_SECRET_KEY 加载)。env 未配置时不构造 store → secret: 前缀值原样回退
    # (warning), 走原明文路径, 向后兼容。在 build_services/register_llm_provider 之前
    # 就地解析, 使同步注册函数拿到明文 api_key。env ISAC_LLM_API_KEY 仍最高优先级
    # (load_config 已写入 llm.api_key, 非 secret: 前缀原样返回)。
    secret_store = _build_secret_store()
    await resolve_secrets_in_config(global_config, secret_store)
    # T4: 启用 LogBuffer 单例, 必须在 setup_logger 之前 (cache_logger_on_first_use 后
    # 装不进 processor 链)。setup_logger 检测单例存在才插入 buffer processor。
    from isac.utils.log_buffer import enable_log_buffer

    enable_log_buffer()
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
    # 互联投递专用 SessionManager: P2 起进程内共享一个实例 (此前每次投递新建,
    # 跨 Agent 会话永不复用, 目标 Agent 每条互联消息都像陌生会话)。
    interagent_session_mgr = SessionManager(global_config)

    # 投递回调: 把 InterAgentMessage 路由到目标 Agent 的 handle_message。
    # 命令 (ask_agent) 现在能拿到 response 而不是恒 None (CODE_REVIEW_REPORT.md #3)。
    async def _deliver_to_agent(target_agent_id: str, message: InterAgentMessage) -> str | None:
        # P2: MEMORY_QUERY 不进 LLM 聊天 —— 按 visible_memory_scopes 裁剪后直接跑
        # 目标 Agent 的记忆检索, 结果经 bus response 同步返回查询方。
        if message.type == "memory_query":
            return await _answer_memory_query(agent_manager, target_agent_id, message)
        # 互联消息复用原消息的 session 上下文; 跨 Agent 时把 from_agent 当作 user_id
        # 让目标 Agent 不会因 has_at=False 而被门控过滤。但目标 Agent 的 handle_message
        # 依赖真实 Session/UserProfile; 这里构造一个最小可路由会话。
        content = message.content
        if message.type == "handoff":
            # P2: 接手方明确知道这是会话交接 (摘要), 而非用户发来的普通消息
            summary = str(message.context.get("summary", "") or message.content)
            content = f"[会话交接] 来自 {message.from_agent} 的交接摘要: {summary}"
        wrapped = ISACMessage(
            msg_id="",
            platform=INTERAGENT_PLATFORM,
            timestamp=0,
            user_id=message.from_agent,
            user_name="",
            group_id=None,
            content=content,
        )
        session = await interagent_session_mgr.get_or_create(wrapped, agent_id=target_agent_id)
        # R2-1: 经会话锁串行化 —— 此前直调 handle_message 绕过 _process_locked 的
        # session_lock, P0 并行下两次并发投递会重叠跑同一互联会话。
        return await agent_manager.handle_message_serialized(target_agent_id, wrapped, session, None)

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
    # P2: handoff_conversation 工具经 services["router"] 登记会话归属转移
    services["router"] = router

    # ── Channel ─────────────────────────────────────────────
    channel_registry = ChannelRegistry()
    _register_channel_adapters(channel_registry, global_config)

    # ── Gateway ─────────────────────────────────────────────
    event_bus = EventBus()
    session_mgr = SessionManager(global_config, db_path=str(DATA_DIR / "gateway" / "sessions.db"))
    # Q1: 跨平台身份映射 SQLite 持久化 (master_id/person_id 跨重启稳定,
    # 人物画像与记忆按归一身份聚合的前提)
    user_mapper = UserMapper(str(DATA_DIR / "gateway" / "identity.db"))
    # S4: 跨平台身份归一器 (默认关闭 → None → 主链路走 user_mapper 原路径, 零行为变化)。
    identity_resolver = _build_identity_resolver(global_config, user_mapper)
    # S4 控制面入口 (bind/conflicts): 放进 services 让 _register_control_plane 透传给
    # create_control_app。仅在 identity.enabled=true 时非空, 默认关闭不挂载路由。
    services["identity_resolver"] = identity_resolver
    session_lock = SessionLockManager()
    # P1: 注入 gateway/channel 句柄到共享 services —— 主动任务强制话轮需要按
    # session_id 反查会话 (session_mgr)、经会话锁串行 (session_lock)、把回复
    # 发回原 Channel (channel_registry); /mute 等命令路径也读 session_mgr。
    services["session_mgr"] = session_mgr
    services["session_lock"] = session_lock
    services["channel_registry"] = channel_registry

    # P0: 消息处理并发化 —— handle_message 只负责派生任务立即返回, 适配器收取
    # 循环不再被单条消息的 LLM 往返阻塞 (跨会话真并行); 单会话仍靠会话锁串行。
    handle_message, drain_inflight = make_message_dispatcher(
        event_bus=event_bus,
        router=router,
        session_mgr=session_mgr,
        user_mapper=user_mapper,
        agent_manager=agent_manager,
        channel_registry=channel_registry,
        metrics=metrics,
        session_lock=session_lock,
        identity_resolver=identity_resolver,
    )

    # 注入 Channel 适配器的消息回调
    for adapter in channel_registry.list():
        adapter.on_message = handle_message

    # ── Alert (规则驱动; 在 start 之前注册, 启动后才挂到 TaskGroup) ──
    # R2-③: WebhookManager 此前已实现但 main 不构造 + AlertManager 不注入 → 死代码。
    # 本轮构造 WebhookManager + EventBus on_async 订阅 + 注入 AlertManager (抽到 helper
    # 降 main 复杂度)。
    webhook_manager = _setup_webhooks(event_bus)
    alert_manager = AlertManager(metrics, webhook_manager=webhook_manager)
    for rule in get_default_alert_rules():
        alert_manager.add_rule(rule)

    # ── 启动编排 (K1): 所有资源通过 register_lifecycle 注册到 runtime ──
    # P0: channels 改到最后注册 (见 runtime.start() 前) —— LIFO 关闭时最先停止
    # 消息入口并 drain 在途任务, 之后才关 journal/usage/providers 等下游资源;
    # 此前 channels 最先注册 → 最后关闭, providers 连接池会在在途消息还没
    # 处理完时先被关掉。启动侧 channels 最后 start 也更合理 (一切就绪才开闸)。
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
            webhook_manager,
            services=services,
            channel_registry=channel_registry,
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

    # C1: shutdown 时关闭 VectorStore/GraphStore 持久连接, 防 WAL/SHM 残留 + FD 泄漏。
    # 此前 storage lifecycle 的 stop 是 _noop_start, 持久连接在进程退出前不显式 close,
    # 嵌入启用时长期运行会让 vectors-<ns>.db 的 WAL/SHM 文件残留 + aiosqlite FD 泄漏。
    runtime.register_lifecycle("storage", _noop_start, lambda: _close_storage_stores(services))

    # J2: 制品存储生命周期 (启动 schema 初始化 + 周期 TTL 扫描; 关闭时 sweep 兜底)。
    # ArtifactStore 在 build_services 中无条件构造, 这里无条件注册: 即使无多模态
    # Provider 注册, start_ttl_sweep 也只是周期扫描空 DB, 开销可忽略。
    artifact_store = services["artifact_store"]
    runtime.register_lifecycle("artifact_store", artifact_store.start, artifact_store.stop)

    # N5b 批次G: 入站媒体 uploads_store 同样需注册生命周期 (start_ttl_sweep 周期清理
    # 7 天过期的下载媒体)。此前只注册了 artifact_store, uploads_store.start 从未被调用
    # → sweep 任务不跑, 入站媒体文件 + DB 行无限堆积 (incoming_media.py 每次 put 写
    # 7 天过期元数据但无人扫)。uploads_store 在 build_services 无条件构造并放入 services
    # (同 artifact_store), 此处无条件注册。
    uploads_store = services["uploads_store"]
    runtime.register_lifecycle("uploads_store", uploads_store.start, uploads_store.stop)

    # J1: 用量存储生命周期 (仅启用计量时注册; stop 时先 flush 缓冲再关连接)。
    _register_usage_lifecycle(runtime, services)
    # J4: 子任务日志生命周期 (仅启用 subagent.enabled 时注册)。
    _register_subagent_lifecycle(runtime, services)

    # P0: channels 最后注册 —— 启动侧一切资源就绪后才开消息闸; 关闭侧 (LIFO
    # 最先执行) 先停适配器收取, 再 drain 在途消息任务, 保证 journal/usage/
    # providers 等下游资源关闭时不再有消息在途 (不丢消息)。
    async def _stop_channels_and_drain() -> None:
        await _shutdown_message_pipeline(channel_registry, drain_inflight, agent_manager)

    runtime.register_lifecycle(
        "channels",
        channel_registry.start_all,
        _stop_channels_and_drain,
    )

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


def _setup_webhooks(event_bus: EventBus) -> Any:
    """R2-③: 构造 WebhookManager + EventBus on_async 订阅 (消息事件 → webhook 推送)。

    WebhookManager 类此前已实现但 main 不构造 + 不订阅 EventBus → 死代码。
    on_async 异常隔离, webhook 推送失败不阻塞主流程。
    """
    from isac.control.webhooks import WebhookManager

    webhook_manager = WebhookManager()

    async def _dispatch_webhook(payload: Any, event_name: str = "") -> None:
        try:
            await webhook_manager.dispatch(event_name, {"event": event_name, "payload": payload})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Webhook 推送失败, 不阻塞主流程", event=event_name, error=str(exc))

    event_bus.on_async(EventType.POST_MESSAGE, lambda p: _dispatch_webhook(p, "post_message"))
    event_bus.on_async(EventType.POST_SEND, lambda p: _dispatch_webhook(p, "post_send"))
    return webhook_manager


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
    webhook_manager: Any = None,
    *,
    services: dict[str, Any] | None = None,
    channel_registry: Any = None,
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
        # Q3 激活: PluginManager 接入 EnableMatrix —— 此前 is_enabled_for 默认放行
        # (enable_matrix=None → True), 部署方无法按 Agent/Channel/全局矩阵控制插件
        # 启用。从 global_config 构造全局 EnableMatrix 注入, 让插件加载后也能参与
        # 矩阵决策 (call_on_load 阶段先全部加载; 真实启用判定在 per-Agent 调用
        # is_enabled_for 时按 Agent 配置 + Channel + 全局三路取交集)。
        plugin_manager = PluginManager(
            plugin_config, enable_matrix=_build_plugin_enable_matrix(services)
        )
        # H2: 隔离插件跑在子进程 (daemon), 优雅关闭时显式终止, 不留残余子进程。
        runtime.register_lifecycle("plugins", _noop_start, plugin_manager.shutdown)
        plugins_dir = Path(control_config.get("plugins_dir", "plugins"))
        # T6: 无条件记录 plugins_dir 供 reload/install/retry 定位 (即使目录尚不存在,
        # 后续经控制面 install 会创建; 否则 reload 报 "plugins_dir 未设置")。
        plugin_manager._plugins_dir = plugins_dir  # noqa: SLF001
        # 用 to_thread 包装 Path.exists 避免 event loop 内 blocking IO (ruff ASYNC240)。
        if await asyncio.to_thread(plugins_dir.exists):
            try:
                load_report = await plugin_manager.load_all(plugins_dir)
                if load_report:
                    logger.info("插件加载完成", report=load_report)
                # CR3-H2/R3: 接线 on_load 生命周期钩子 + 插件注册表/兼容层桥接。
                # 此前 call_on_load 全仓无调用点, 插件即使被加载也是"惰性"的
                # (无法注册事件订阅/互联钩子/Admin Route)。event_bus/inter_agent_bus/
                # router 都是生产实例, 插件经 on_event_intercept/on_event_async 的
                # 订阅会真实参与 process_message 主链路。R3 起 tools/commands/
                # prompt_builder 改为进程级共享注册表 (services["plugin_tools"] 等),
                # native 插件 on_load register 真实写入, 兼容层 (AstrBot/MaiBot) 经
                # _adapt_compat_plugins 桥接 @filter.llm_tool/@register_action;
                # assemble_agent 合并进 per-Agent registry。详见 _fire_plugin_on_load docstring。
                await _fire_plugin_on_load(
                    plugin_manager, services or {}, event_bus=event_bus, bus=bus, router=router
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("插件加载过程异常, 不阻塞控制面", error=str(exc), exc_info=True)

        # CR3-L3: BM25 内存索引解析器 (namespace → SparseBM25Index), 让治理路由的
        # delete/restore/correct 能同步内存索引。
        sparse_indexes = (services or {}).get("sparse_indexes") or {}
        # S5 (O3): 工作流引擎 (默认关闭: control.workflow.enabled!=true → None → 路由
        # 不挂载, 零行为变化)。启用时构造并注入, WorkflowEngine 按 base_dir 持久化实例。
        # S5 激活: 同时注入生产 action_handler + condition_evaluator + 声明式加载。
        workflow_engine = _build_workflow_engine(control_config, agent_manager)
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
            workflow_engine=workflow_engine,
            identity_resolver=(services or {}).get("identity_resolver"),
            vector_resolver=(services or {}).get("vector_resolver"),
            channel_registry=channel_registry,
            webhook_manager=webhook_manager,
            tenant_manager=(services or {}).get("tenant_manager"),
            services=services or {},
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
        # R2-④: MCP Server stdio 启动点 (抽到 helper 降 _register_control_plane 复杂度)
        _register_mcp_server(runtime, control_config, services, agent_manager, router, bus, plugin_manager)
    except Exception as exc:
        logger.error("控制面注册失败 (不阻塞数据面)", error=str(exc), exc_info=True)


def _register_mcp_server(
    runtime: ApplicationRuntime,
    control_config: dict[str, Any],
    services: dict[str, Any] | None,
    agent_manager: AgentManager,
    router: MessageRouter,
    bus: InterAgentBus,
    plugin_manager: Any,
) -> None:
    """R2-④: MCP Server 生产启动点 (control.mcp_server.enabled, 默认关闭零行为变化)。

    ISACMCPServer 类此前已完整 (除 5 工具本轮补齐), 但生产无启动点 → 死代码。
    启用时 spawn stdio task (NDJSON over stdin/stdout), 供 MCP 客户端编排。
    """
    mcp_cfg = (control_config.get("mcp_server", {}) or {}) if isinstance(control_config, dict) else {}
    if not mcp_cfg.get("enabled"):
        return
    from isac.control.auth import parse_token_scopes
    from isac.control.mcp_server import ISACMCPServer

    # Fix-42: 传入 parsed_tokens —— 此前只传 api_token, tokens[] 部署 (scope 模型)
    # 下 mcp_server 的认证条件 (api_token or parsed_tokens) 为假, tools/call
    # 认证整段被跳过 → MCP 通道零认证执行管理工具。
    mcp_server = ISACMCPServer(
        services or {},
        api_token=str(control_config.get("api_token", "")),
        parsed_tokens=parse_token_scopes(control_config),
        agent_manager=agent_manager,
        router=router,
        bus=bus,
        plugin_manager=plugin_manager,
    )

    async def _start_mcp() -> None:
        runtime.spawn(mcp_server.serve_stdio(), name="mcp-server-stdio")

    async def _stop_mcp() -> None:
        # serve_stdio 读 stdin 循环, 关闭时 stdin EOF 自然退出; 无显式 stop。
        pass

    runtime.register_lifecycle("mcp_server", _start_mcp, _stop_mcp)
    logger.info("MCP Server 已注册 (stdio)", token=bool(control_config.get("api_token")))


def _build_workflow_engine(control_config: dict[str, Any], agent_manager: AgentManager) -> Any:
    """S5: 按 control.workflow 配置构造 WorkflowEngine + 注入 action_handler /
    condition_evaluator + 声明式加载工作流定义文件 (抽到 helper 避免 _register_
    control_plane 复杂度超 C901 上限)。

    默认关闭 (control.workflow.enabled!=true → None); Agent 工具入口 (Agent 主动
    触发 workflow) 是 P5 决策项, 有意未做 (避免半接线死代码)。
    """
    workflow_cfg = (control_config.get("workflow", {}) or {}) if isinstance(control_config, dict) else {}
    if not workflow_cfg.get("enabled"):
        return None
    from isac.runtime.workflow.actions import (
        build_default_action_handler,
        build_default_condition_evaluator,
    )
    from isac.runtime.workflow.engine import WorkflowEngine
    from isac.runtime.workflow.loader import load_workflows_from_dir

    engine = WorkflowEngine(
        base_dir=str(workflow_cfg.get("base_dir") or (DATA_DIR / "workflows"))
    )
    engine.set_action_handler(build_default_action_handler(agent_manager))
    engine.set_condition_evaluator(build_default_condition_evaluator())
    definitions_dir = workflow_cfg.get("definitions_dir")
    if definitions_dir:
        loaded = load_workflows_from_dir(engine, str(definitions_dir))
        if loaded:
            logger.info("工作流定义已声明式加载", count=loaded, dir=str(definitions_dir))
    return engine


async def _fire_plugin_on_load(
    plugin_manager: Any,
    services: dict[str, Any],
    *,
    event_bus: Any = None,
    bus: Any = None,
    router: Any = None,
) -> None:
    """R3: 构造 PluginContext + 触发 native 插件 on_load + 桥接兼容层插件装饰器。

    agent_hooks 是进程级共享注册表 (services["plugin_agent_hooks"]), 组装每个
    Agent 时由 assemble_agent 合并进该 Agent 的私有 hooks; event_bus 缺失
    (极少数测试路径) 时跳过, 不构造无效 context。失败只记日志不阻塞启动。

    R3 (收敛 Q3): 此前 PluginContext 的 tools/commands/prompt_builder 留 None
    (注释明示"per-Agent 桥接见 P 节点"), 导致 native 插件 on_load 调
    register_tool/register_command/register_injector 会 raise (被 call_on_load
    按插件隔离吞掉), 兼容层 (AstrBot/MaiBot) @filter.llm_tool/@register_action
    标记的 handler 是死代码。本轮复用 plugin_agent_hooks 三阶段共享模式: 建立
    进程级共享 ToolRegistry/CommandRegistry/SystemPromptBuilder 注入
    PluginContext, native 插件 on_load register 写入共享表; 随后调
    _adapt_compat_plugins 把兼容层插件装饰器标记桥接进共享表。assemble_agent
    再把共享表合并进 per-Agent registry (见 assembly.py)。
    """
    if event_bus is None:
        logger.debug("event_bus 未注入, 跳过插件 on_load 接线")
        return
    try:
        from isac.agent.hooks import AgentHooks
        from isac.agent.prompt_builder import SystemPromptBuilder
        from isac.agent.tools.registry import ToolRegistry
        from isac.commands.registry import CommandRegistry
        from isac.plugin.native.plugin import make_plugin_context

        # R3: 进程级共享注册表 (仿 plugin_agent_hooks 三阶段模式)。裸 ToolRegistry()
        # 无策略仅作收集器; assemble_agent 合并进 per-Agent registry 时由 per-Agent
        # 的 permission/enable_matrix 控可见性。setdefault 幂等, 多次调用安全。
        shared_tools = services.setdefault("plugin_tools", ToolRegistry())
        shared_commands = services.setdefault("plugin_commands", CommandRegistry())
        shared_prompt = services.setdefault("plugin_prompt_builder", SystemPromptBuilder())
        plugin_agent_hooks = services.setdefault("plugin_agent_hooks", AgentHooks())

        context = make_plugin_context(
            agent_hooks=plugin_agent_hooks,
            event_bus=event_bus,
            services=services,
            inter_agent_bus=bus,
            router=router,
            tools=shared_tools,
            commands=shared_commands,
            prompt_builder=shared_prompt,
        )
        on_load_report = await plugin_manager.call_on_load(context)
        if on_load_report:
            logger.info("插件 on_load 完成", report=on_load_report)

        # R3: 桥接兼容层插件 (AstrBot/MaiBot) 的装饰器标记到共享注册表。
        # native 插件经 on_load 主动 register; 兼容层插件靠 adapter 扫描标记。
        await _adapt_compat_plugins(plugin_manager, shared_tools, shared_commands)
    except Exception as exc:  # noqa: BLE001
        logger.warning("插件 on_load 接线失败, 不阻塞控制面", error=str(exc), exc_info=True)


async def _adapt_compat_plugins(
    plugin_manager: Any,
    shared_tools: Any,
    shared_commands: Any,
) -> None:
    """R3: 遍历已加载的 AstrBot/MaiBot 兼容层插件, 调 adapter.adapt 桥接装饰器标记。

    loader 加载兼容层插件后只 exec_module+实例化, 不调 adapt →
    @filter.llm_tool / @register_action 标记的 handler 在生产是死代码。本函数
    补齐: 对每个 AstrBot Star 实例调 AstrBotStarAdapter.adapt 注册 tools; 对每个
    MaiBot 插件实例调 MaiBotPluginAdapter.adapt 注册 tools+commands。逐插件错误
    隔离, 失败不阻塞其他插件。call_on_load 已显式跳过非 native (manager.py:239),
    故兼容层插件不在此前经 PluginContext.on_load, 必须经本函数桥接。
    """
    try:
        from isac.plugin.compatibility.astrbot.adapter import AstrBotStarAdapter
        from isac.plugin.compatibility.maibot.plugin import MaiBotPluginAdapter
    except ImportError as exc:
        logger.debug("兼容层适配器不可用, 跳过桥接", error=str(exc))
        return

    loaded: dict[str, Any] = getattr(plugin_manager, "_loaded", {})
    for name, plugin in loaded.items():
        instance = getattr(plugin, "instance", None)
        if instance is None:
            continue
        try:
            if getattr(plugin, "is_astrbot", lambda: False)():
                result = await AstrBotStarAdapter(instance).adapt(shared_tools)
                if result.get("tools") or result.get("hooks"):
                    logger.info(
                        "AstrBot 插件已桥接", plugin=name,
                        tools=result.get("tools"), pending_hooks=result.get("hooks"),
                    )
            elif getattr(plugin, "is_maibot", lambda: False)():
                result = await MaiBotPluginAdapter(instance).adapt(
                    shared_tools, shared_commands
                )
                if result.get("tools") or result.get("commands"):
                    logger.info(
                        "MaiBot 插件已桥接", plugin=name,
                        tools=result.get("tools"), commands=result.get("commands"),
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("兼容层插件桥接失败, 跳过该插件", plugin=name, error=str(exc), exc_info=True)


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
