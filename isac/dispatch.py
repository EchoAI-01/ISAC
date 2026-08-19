"""U2 消息主链路 (dispatch): 入站消息 → 身份归一 → 媒体落盘 → 门控路由 →
Agent Loop → 回复出站 (含 artifact 扫描与进度通知)。

原 isac/main.py 消息管线拆出 (U2 装配层重构); main.py 保留薄入口 re-export。
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
from isac.gateway.event_bus import EventBus
from isac.gateway.identity.resolver import IdentityResolver
from isac.gateway.incoming_media import download_inbound_media
from isac.gateway.lock import SessionLockManager, conversation_lock_key
from isac.gateway.models import UserProfile
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.observability import MetricsCollector, get_default_metrics
from isac.outbound import _append_artifact_segments as _append_artifact_segments
from isac.outbound import _make_progress_sender, _send_reply
from isac.router.router import MessageRouter
from isac.runtime.manager import AgentManager
from isac.utils.logger import get_logger

logger = get_logger(__name__)

DATA_DIR = Path("data")

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


def _maybe_consume_approval_reply(
    message: ISACMessage, agent_manager: Any, metrics: MetricsCollector
) -> bool:
    """U5: 若消息是 ask 档审批回复 ("同意/拒绝 <审批码>") 则消费并返回 True。

    HITL 的 IM 回流路径: 审批回复直达 ApprovalGate 决定 pending 审批, 不触发常规
    对话回合。approval_gate 未注入 / 消息非审批回复 / 审批码已过期时返回 False,
    调用方继续走正常路由。抽自 process_message (降 C901)。
    """
    approval_gate = getattr(agent_manager, "_services", {}).get("approval_gate")
    if approval_gate is None:
        return False
    parsed = approval_gate.parse_reply(message.content)
    if parsed is None:
        return False
    approval_id, verdict = parsed
    decider = f"human:{message.platform}:{message.user_id}"
    # Fix-90: 来源会话绑定 —— 审批卡片 (含审批码) 发回原会话, 群聊中任何成员
    # (或得知审批码的其他会话用户) 都可见; 此前 decide 只按审批码查表不校验来源,
    # HITL 门被旁路。现把来源会话 (platform:group/user:<id>) 与发起人 user_id
    # 交给 decide 校验: 不匹配的回复按普通消息继续路由, 不消费。
    target = f"group:{message.group_id}" if message.group_id else f"user:{message.user_id}"
    conversation = f"{message.platform}:{target}"
    if not approval_gate.decide(
        approval_id, verdict, decider=decider,
        conversation=conversation, user_id=message.user_id,
    ):
        return False  # 审批码未知/已过期/来源不匹配 → 按普通消息继续路由
    metrics.counter("isac_messages_dropped_total").inc()
    return True


async def _download_inbound_media_safe(routed_message: ISACMessage, agent_manager: Any) -> None:
    """R1-②: 入站媒体下载落盘 (失败不阻塞主链路; 抽自 process_message 降 C901)。

    扫 routed_message.segments 的 image/voice/video/file, HTTP 下载为 bytes →
    uploads_store.put → 回填 media_uri 供工具经 MediaNormalizer 读。uploads_store
    为 None (未启用) 或无 media segment 时直接跳过, 零行为变化。
    """
    uploads_store = getattr(agent_manager, "_services", {}).get("uploads_store")
    if uploads_store is None:
        return
    # Fix-99: OneBot/NapCat 同机部署的媒体 URL 是 loopback, 默认 SSRF 守卫会拒;
    # 经 global_config inbound_media.allow_loopback 显式放行 (仍逐跳复校验)。
    global_config = getattr(agent_manager, "_services", {}).get("global_config", {}) or {}
    allow_loopback = bool((global_config.get("inbound_media", {}) or {}).get("allow_loopback", False))
    try:
        await download_inbound_media(routed_message, uploads_store, allow_loopback=allow_loopback)
    except Exception as exc:  # noqa: BLE001 入站下载失败不阻塞消息主链路
        logger.warning("入站媒体下载落盘异常, 继续", error=str(exc))


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

    # U5: 审批回复拦截 —— "同意/拒绝 <审批码>" 直达 ApprovalGate, 不作对话处理。
    if _maybe_consume_approval_reply(message, agent_manager, metrics):
        return

    decision = await router.route(message)
    if decision is None:
        metrics.counter("isac_messages_dropped_total").inc()
        return  # 路由无匹配 → DROP
    routed_message = dataclasses.replace(message, content=decision.content)

    # R1-②: 入站媒体下载落盘 (uploads_store 未启用/无 media segment 时跳过)。
    await _download_inbound_media_safe(routed_message, agent_manager)

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
    # Fix-113: session_mgr.get_or_create 会把 message.session_id 改写为**它创建/
    # 恢复的那个会话**的内部 id (副作用)。下方 observer/candidate 各自 get_or_create
    # 后, message.session_id 停留在最后一个 observer/candidate 的会话 id 上 ——
    # 仲裁未切换回复者时, 主链路 (handle_message/出站/事件流) 会带着别人的会话 id
    # 继续处理 primary 的消息。进入 mesh 路由前先快照 primary 的会话 id, 退出时还原
    # (仲裁切换路径由调用方对 final_agent 重新 get_or_create, 再次改写是预期行为)。
    primary_session_id = message.session_id
    # observer 旁听: 后台并发写各自记忆, 不阻塞 primary 回复 (R2-3)。get_or_create
    # 是内存操作可直接 await; 真正耗时的 observe_message (store_episode 可能含
    # embedding 调用) 派生为后台任务, 由 AgentManager._memory_tasks 承接并在优雅
    # 关闭时 drain。
    for observer_id in mesh_decision.observer_agent_ids:
        observer_session = await session_mgr.get_or_create(message, agent_id=observer_id)
        agent_manager.schedule_observe_message(observer_id, message, observer_session, profile)
    if not mesh_decision.candidate_agent_ids:
        message.session_id = primary_session_id
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
    message.session_id = primary_session_id
    return winner or decision.agent_id


async def _cancel_lingering_tasks(tasks: set[asyncio.Task[None]]) -> None:
    """2026-08-19 (M5): 取消 drain 超时后的残留任务并 gather 收尾。

    抽出独立函数既复用取消语义, 也让 make_message_dispatcher 的嵌套分支不堆叠
    (C901)。_process_locked 的 finally 会在取消传播时释放会话锁。
    """
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


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
        # 2026-08-19 Critical 修复: 锁键必须与会话键同粒度 (群聊按 group 聚合, 忽略
        # user_id)。此前锁键含 user_id, 同群不同成员拿不同锁却并发跑同一会话: 事件流
        # 交织、THINKING 互踩、互相打断。统一走 conversation_lock_key 权威派生
        # (与 _run_forced_turn / 跨 Agent 投递同一键空间)。
        lock_key = conversation_lock_key(message.platform, message.user_id, message.group_id)
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
            # 2026-08-19 (M5): 超时后必须取消残留任务 —— 此前只记 warning 不取消,
            # 随后 LIFO 链关闭 providers/store, 残留任务在已关闭资源上继续运行并各自
            # 抛错, 优雅关闭的"不丢消息"承诺在超时分支不成立。
            logger.warning("在途消息处理未在超时内完成, 取消残留任务", count=len(still_pending))
            await _cancel_lingering_tasks(still_pending)

    return handle_message, drain_inflight


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
        scheduler = instance.services.proactive_scheduler
        if scheduler is not None:
            await scheduler.stop()
        # R3: 断开该 Agent 的 MCPClient (子进程/HTTP 连接), 避免关闭时泄漏。
        await agent_manager._disconnect_mcp_clients(instance)  # noqa: SLF001


async def _noop_start() -> None:
    """无启动动作的资源 (如 Provider 连接池: 惰性创建, 无需 start) 占位。"""
    return None
