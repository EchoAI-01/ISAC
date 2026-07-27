"""AgentManager: Agent 生命周期管理 (ARCHITECTURE.md 3.1 / SPECIFICATION.md 2.8)。

所有公开方法同时暴露给控制面 (Admin API / MCP Server)，control/ 不复制业务逻辑。
"""

from __future__ import annotations

import asyncio
import builtins
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from isac.core.constants import DEFAULT_AGENT_ID, INTERAGENT_PLATFORM
from isac.core.exceptions import AgentNotFoundError
from isac.gating.types import GateKind
from isac.runtime.assembly import assemble_agent
from isac.runtime.config import AgentConfig
from isac.runtime.conversation import (
    ConversationSnapshot,
    ConversationState,
    ForcedTurnState,
    WaitEndReason,
)
from isac.runtime.instance import AgentInstance
from isac.utils.logger import get_logger
from isac.utils.logging_context import bind_log_context

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from isac.channel.model import ISACMessage
    from isac.core.types import ProgressEvent
    from isac.gateway.models import Session, UserProfile
    from isac.runtime.conversation import ConversationRuntime, ProactiveTask
    from isac.runtime.progress import ProgressReporter

logger = get_logger(__name__)

# D9: instance.progress_reporters 的 session 数量软上限, 防止长期运行无界增长
# (超出时丢弃最旧插入的 session, 与 WebChatAdapter._pending_replies 的 FIFO 上限同思路)。
MAX_PROGRESS_REPORTERS_PER_AGENT = 500

# Q1: 每次互动的关系深度增量 (线性累积, 封顶 1.0 ≈ 100 次互动后达到最深)。
RELATIONSHIP_DEPTH_STEP = 0.01


class AgentManager:
    """Agent 生命周期管理器。

    [桩] 内存实现; 待 registry.jsonc 持久化与重启恢复 running 状态落地。
    """

    def __init__(self, services: dict[str, Any]):
        """
        Args:
            services: 共享服务 (provider_manager / memory_factory / global_config / ...)
        """
        self._agents: dict[str, AgentInstance] = {}
        self._services = services
        # Fix-2: 按 agent_id 的配置锁, 用于 PATCH 时把"读 revision → 校验 if_match →
        # 合并 → 持久化 → reload_config"整段串行化, 避免并发 PATCH 静默丢更新。
        # agent_id 数量受限于实际创建过的 Agent 数 (不像 session 那样量级无界),
        # 不需要 SessionLockManager 那种引用计数回收, destroy() 时清理即可。
        self._config_locks: dict[str, asyncio.Lock] = {}
        # Q1: 记忆写入后台任务的强引用集合 (create_task 结果不持引用会被 GC 取消;
        # done 回调自清理, 集合大小受在途写入数约束, 不会无界增长)。
        self._memory_tasks: set[asyncio.Task[None]] = set()

    # ── 生命周期 (控制面暴露) ──────────────────────────────

    async def create(self, config: AgentConfig) -> AgentInstance:
        """创建并组装 Agent (默认 stopped，需 start 后才处理消息)。

        assemble_agent 内部 memory_factory 返回 NoOpMemoryPipeline 或真实 MemoryRetrievalPipeline;
        真实 pipeline 有 warm_up_sparse_index 方法, 从 MetadataStore 重建 BM25 内存索引,
        让重启后 BM25 检索立即可用而不等下次写入 (K3, DEVELOPMENT_PLAN.md)。
        """
        if config.agent_id in self._agents:
            raise ValueError(f"Agent 已存在: {config.agent_id}")
        instance = await assemble_agent(config, self._services)
        self._agents[config.agent_id] = instance
        # K3: 预热 Sparse 索引 (NoOpMemoryPipeline 没有此方法, 静默跳过)
        warm = getattr(instance.memory, "warm_up_sparse_index", None)
        if warm is not None:
            try:
                await warm()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Sparse 索引预热失败, 不阻塞 Agent 创建", agent_id=config.agent_id, error=str(exc))
        self._inc_metric("isac_agent_creates_total")
        logger.info("Agent 已创建", agent_id=config.agent_id)
        return instance

    async def start(self, agent_id: str) -> None:
        instance = self._require(agent_id)
        instance.status = "running"
        # P1(L3): conversation 启用时随 Agent 启动主动任务调度循环 (assembly 仅在
        # conversation.enabled=true 时构造 scheduler, 默认 None 零行为变化)。
        scheduler = instance.services.get("proactive_scheduler")
        if scheduler is not None:
            await scheduler.start(self._on_proactive_wake)
        self._inc_metric("isac_agent_starts_total")
        self._update_active_gauge()
        logger.info("Agent 已启动", agent_id=agent_id)

    async def stop(self, agent_id: str) -> None:
        instance = self._require(agent_id)
        instance.status = "stopped"
        scheduler = instance.services.get("proactive_scheduler")
        if scheduler is not None:
            await scheduler.stop()
        self._inc_metric("isac_agent_stops_total")
        self._update_active_gauge()
        logger.info("Agent 已停止", agent_id=agent_id)

    async def destroy(self, agent_id: str, *, keep_memory: bool = True) -> None:
        """销毁 Agent。keep_memory=True 时保留记忆数据。"""
        instance = self._require(agent_id)
        del self._agents[agent_id]
        self._config_locks.pop(agent_id, None)
        scheduler = instance.services.get("proactive_scheduler")
        if scheduler is not None:
            await scheduler.stop()
        self._update_active_gauge()
        # Q0: 失效独立 Provider 缓存 (否则重建同名 Agent 仍拿到旧 llm 配置的 Provider)
        await self._invalidate_agent_provider(agent_id)
        if not keep_memory:
            await self._purge_memory(instance)
        logger.info("Agent 已销毁", agent_id=agent_id, keep_memory=keep_memory)

    async def _invalidate_agent_provider(self, agent_id: str) -> None:
        """Q0: 让 ProviderManager 丢弃该 Agent 的独立 Provider 缓存并释放连接池。

        此前缓存全仓无失效点: PATCH 修改 AgentConfig.llm 后 for_agent 仍返回旧
        Provider (换模型必须重启进程), destroy 后重建同名 Agent 也继承旧凭据。
        """
        provider_manager = self._services.get("provider_manager")
        if provider_manager is None:
            return
        invalidate = getattr(provider_manager, "invalidate_agent_provider", None)
        if invalidate is None:
            return
        try:
            await invalidate(agent_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Agent Provider 缓存失效失败, 已忽略", agent_id=agent_id, error=str(exc))

    @staticmethod
    async def _purge_memory(instance: AgentInstance) -> None:
        """Q0: keep_memory=False 时清理该 Agent 命名空间的记忆数据 (原 TODO 落地)。

        经 instance.memory (pipeline) 取已含租户前缀的 namespace 与 MetadataStore,
        硬删 episodes/person_profiles/jargon_entries 并清空 BM25 内存索引。
        shared 命名空间被多 Agent 共享, 一律拒绝清理。向量分库文件保留: 孤儿向量
        经 get_episodes_by_ids 的 ACL 过滤不会泄露, 文件按 namespace 隔离。
        """
        pipeline = instance.memory
        namespace = str(getattr(pipeline, "namespace", "") or "")
        metadata = getattr(pipeline, "metadata", None)
        if metadata is None or not namespace:
            return  # NoOpMemoryPipeline / memory 未启用: 无可清理数据
        if namespace == "shared" or namespace.endswith(":shared"):
            logger.warning("shared 记忆命名空间被多 Agent 共享, 拒绝清理", namespace=namespace)
            return
        try:
            removed = await metadata.delete_namespace(namespace)
            sparse = getattr(pipeline, "sparse", None)
            if sparse is not None:
                sparse.clear()
            logger.info("Agent 记忆已清理", namespace=namespace, episodes_removed=removed)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Agent 记忆清理失败, 已忽略", namespace=namespace, error=str(exc))

    def acquire_config_lock(self, agent_id: str) -> asyncio.Lock:
        """按 agent_id 取配置锁 (Fix-2, 不存在则创建)。

        供控制面 PATCH 端点 ``async with manager.acquire_config_lock(agent_id):``
        包住整段"读取当前配置 → 校验 If-Match → 合并 → 持久化 → reload_config",
        使同一 agent_id 的并发 PATCH 严格串行, 不会互相用过期的基线覆盖对方的改动。
        """
        lock = self._config_locks.get(agent_id)
        if lock is None:
            lock = asyncio.Lock()
            self._config_locks[agent_id] = lock
        return lock

    async def get(self, agent_id: str) -> AgentInstance | None:
        return self._agents.get(agent_id)

    async def list(self) -> list[AgentInstance]:
        return list(self._agents.values())

    async def list_ids(self) -> builtins.list[str]:
        """已加载的 agent_id 列表 (供重启恢复去重用)。"""
        return list(self._agents.keys())

    async def reload_config(self, agent_id: str, config: AgentConfig) -> None:
        """热更新配置 (重建子系统中受配置影响的部分)。

        TODO: 差量更新 gating/persona/权限, 避免整实例重建。
        """
        old_instance = self._require(agent_id)
        was_running = old_instance.status == "running"
        # P1: 停掉旧实例的主动调度循环 (新实例随 running 状态重启自己的)
        old_scheduler = old_instance.services.get("proactive_scheduler")
        if old_scheduler is not None:
            await old_scheduler.stop()
        # Q0: 失效独立 Provider 缓存, PATCH 修改 llm 后 for_agent 才会按新配置重建
        await self._invalidate_agent_provider(agent_id)
        instance = await assemble_agent(config, self._services)
        instance.status = "running" if was_running else "stopped"
        self._agents[agent_id] = instance
        if was_running:
            new_scheduler = instance.services.get("proactive_scheduler")
            if new_scheduler is not None:
                await new_scheduler.start(self._on_proactive_wake)
        logger.info("Agent 配置已重载", agent_id=agent_id)

    # ── 消息处理入口 (由 MessageRouter 经依赖注入调用) ─────

    async def handle_message(
        self,
        agent_id: str,
        message: ISACMessage,
        session: Session,
        user_profile: UserProfile | None,
        progress_sender: Callable[[str, ProgressEvent], Awaitable[None]] | None = None,
    ) -> str | None:
        """处理一条路由到本 Agent 的消息，返回回复文本 (WAIT/DROP 返回 None)。

        [已完成] GatingContext 完整构造 (has_at/has_mention/effective_frequency/
        recent_self_replies/recent_window_messages);
        待落地: pending 消息队列与积压评估 (当前为单条即时处理, pending_count 恒为 1)。
        """
        instance = await self.get(agent_id)
        if instance is None or instance.status != "running":
            logger.warning("Agent 不存在或未运行，消息忽略", agent_id=agent_id)
            return None

        # 可观测性: trace_id/session_id/agent_id 经 contextvars 贯穿整段处理,
        # 其后所有日志 (门控 → Loop → 工具 → 记忆 → 回复) 自动携带这三个字段,
        # 便于按一次消息处理串联排查。退出 with 时精确还原, 不污染后续。
        with bind_log_context(
            trace_id=uuid.uuid4().hex,
            session_id=session.session_id,
            agent_id=agent_id,
        ):
            logger.debug("消息进入 Agent 处理", content_len=len(message.content))
            return await self._dispatch_message(instance, message, session, user_profile, progress_sender)

    async def handle_message_serialized(
        self,
        agent_id: str,
        message: ISACMessage,
        session: Session,
        user_profile: UserProfile | None,
        progress_sender: Callable[[str, ProgressEvent], Awaitable[None]] | None = None,
    ) -> str | None:
        """R2-1: 经会话锁串行化的 handle_message —— 供跨 Agent 投递 (bus → _deliver_to_agent) 复用。

        普通消息入口在 dispatcher 的 `_process_locked` 里已被 session_lock 包裹, 但 bus
        投递此前直调 handle_message 完全绕过锁: P0 跨会话真并行后, 两次并发指向同一
        (目标 Agent, 互联会话) 的投递会重叠跑同一会话的门控/Loop/会话状态机, 破坏
        "单会话串行"。这里用与 `_run_forced_turn` 一致的 acquire/release 配对补锁; 锁键
        含 target agent_id, 精确隔离到"目标 Agent × 会话"(不同目标/不同来源仍并行)。

        锁键的平台段对互联消息恒为 INTERAGENT_PLATFORM, 与普通入口的
        `platform:user:group` 键天然不同 —— 互联会话与普通会话本就是两套独立命名空间,
        不应互相阻塞。session_lock 未注入时退化为直调 (与旧行为一致)。

        注意: 普通入口 process_message 已在锁内, 不得改走本方法 (asyncio.Lock 不可重入)。
        """
        lock_mgr = self._services.get("session_lock")
        if lock_mgr is None:
            return await self.handle_message(agent_id, message, session, user_profile, progress_sender)
        lock_key = (
            f"{session.platform}:{agent_id}:"
            f"{session.user_id or 'unknown'}:{session.group_id or 'private'}"
        )
        lock = await lock_mgr.acquire(lock_key)
        acquired = False
        try:
            await lock.acquire()
            acquired = True
            return await self.handle_message(agent_id, message, session, user_profile, progress_sender)
        finally:
            if acquired:
                lock.release()
            lock_mgr.release(lock_key)

    async def _dispatch_message(
        self,
        instance: AgentInstance,
        message: ISACMessage,
        session: Session,
        user_profile: UserProfile | None,
        progress_sender: Callable[[str, ProgressEvent], Awaitable[None]] | None,
    ) -> str | None:
        """在 handle_message 已绑定的日志上下文内执行 门控 → Loop → 回复。"""
        agent_id = instance.agent_id
        conv_runtime = self._conversation_runtime_for(instance, session, message)
        # 每条到达消息都累加注入器的新消息计数 (按 session 隔离, 支撑 max_new_messages 频率控制)。
        instance.prompt_builder.notify_new_message(session.session_id)

        # 同步记录到该 session 独立的 TurnScheduler 滑窗，供 effective_frequency / 存在感惩罚计算。
        turn_scheduler = instance.gating.get_turn_scheduler(session.session_id)
        turn_scheduler.record_window_message()

        # E4: 命令拦截 (在门控前)。/cmd 是用户显式发起, 跳过门控。
        if instance.commands is not None and message.content.startswith("/"):
            cmd_result = await self._try_command(instance, message, session, user_profile)
            if cmd_result is not None:
                turn_scheduler.record_reply()
                instance.gating.get_idle_backoff(session.session_id).record_reply()
                return cmd_result

        if await self._debounce_should_yield(instance, conv_runtime, message):
            return None

        # MVP-Fix: drain 提到门控之前。此前 ① 门控只评估末条消息 —— 突发里靠前
        # 消息的 @提及/内容分被丢弃, 整个突发可能一条不回; ② drain 为空时退回用
        # 本条内容再跑一轮 —— 突发中被别的回合合并处理过的消息会重复回复。
        # 现在 drain 空即弃权 (根治重复), 门控与 Loop 都基于整个 burst。
        pending = self._drain_pending(conv_runtime, message)
        if not pending:
            logger.debug("本条消息已被前一回合合并处理, 弃权避免重复回复", agent_id=agent_id)
            return None

        # P2: 互联消息 (ask/notify/handoff 经 bus 投递) 已过 Link ACL, 是显式协作
        # 动作, 不适用环境聊天的回复必要性门控 —— 否则 notify/交接摘要可能被静默
        # WAIT 掉 (投递"成功"但目标从未处理), ask 发起方拿到空响应。
        if message.platform != INTERAGENT_PLATFORM:
            gating_context = self._build_gating_context(
                instance, pending, session, user_profile, turn_scheduler, conv_runtime
            )
            decision = await instance.gating.evaluate(pending, gating_context)
            if decision.kind != GateKind.TRIGGER:
                logger.debug("门控未触发", agent_id=agent_id, kind=decision.kind.value)
                return None

        agent_context = self._build_agent_context(
            instance, message, session, user_profile, progress_sender, conv_runtime
        )
        # P1(L2): 积压 >1 条时合并为一轮输入 (带说话人前缀多行)
        user_content = self._merge_pending_content(pending)
        messages = [{"role": "user", "content": user_content}]
        result = await self._run_loop_with_conversation(instance, conv_runtime, messages, agent_context)
        if result.interrupted:
            logger.info("本轮被新消息打断, 旧回复已抑制", agent_id=agent_id)
            return None
        if result.content:
            # 话轮调度: 记录本轮回复, 更新滑窗频率与存在感数据。
            turn_scheduler.record_reply()
            instance.gating.get_idle_backoff(session.session_id).record_reply()
            # Q1: 回复后异步写入记忆 (episodic + 画像回路), 不阻塞回复发送。
            # MVP-Fix: 写入**本回合实际看到的输入** (合并后的整个 burst), 而不是
            # 触发这一轮的单条 —— 否则突发被合并处理时, 记忆只留下其中一条,
            # 用户后来问起前面说过的内容检索不到。
            self._schedule_memory_write(
                instance, message, session, user_profile, result.content, user_content
            )
        return result.content or None

    async def _debounce_should_yield(
        self,
        instance: AgentInstance,
        conv_runtime: ConversationRuntime | None,
        message: ISACMessage,
    ) -> bool:
        """P1(L2): 等待 debounce 静默窗口; 返回 True 表示本条应弃权。

        窗口内若有更新消息到达 (锁外 notify_incoming 已缓存并刷新
        last_message_received_at), 本条弃权, 由最新消息的处理统一 drain 合并,
        避免连续消息逐条打断。
        MVP-Fix: 互联消息 (ask/notify/handoff) 豁免 —— 它们已过 Link ACL, 是显式
        协作动作, 不该被静默窗口延迟, 更不该因"窗口内有新消息"被弃权 (与门控
        豁免同源: 投递"成功"但目标从未处理)。
        """
        if conv_runtime is None or message.platform == INTERAGENT_PLATFORM:
            return False
        debounce_seconds = self._conversation_debounce_seconds(instance)
        if debounce_seconds <= 0:
            return False
        await asyncio.sleep(debounce_seconds)
        if conv_runtime.should_trigger(debounce_seconds):
            return False
        logger.debug("debounce 静默窗口内有更新消息, 本条并入后续合并处理")
        return True

    def _conversation_runtime_for(
        self, instance: AgentInstance, session: Session, message: ISACMessage
    ) -> ConversationRuntime | None:
        """P1(L1/L2): 取会话拟人运行时 (conversation 关闭时 None, 零行为变化)。

        消息一般已在锁外 notify_incoming 缓存 (P0 dispatcher 的 pre-lock 信号);
        直调 handle_message 的旧调用方/测试未走该路径, 去重后兜底补注册。

        MVP-Fix: 去重键改用 **msg_id** 而非对象身份 —— `process_message` 传给
        本方法的是 `dataclasses.replace(message, content=...)` 的**新对象**, 与
        notify_incoming 缓存的原对象身份不同, 身份去重永远不命中 → 每条消息被
        缓存两次: 突发合并把重复条目一起喂给 LLM, 且末条的 drain 非空导致重复
        回复。msg_id 在 replace 后保持不变, 是稳定去重键 (为空时回退身份比较)。
        """
        conv_registry = instance.services.get("conversation_registry")
        if conv_registry is None or not self._conversation_enabled():
            return None
        conv_runtime = conv_registry.get(instance.agent_id, session.session_id)
        if not self._is_cached(conv_runtime, message):
            conv_runtime.register_message(message)
        return conv_runtime

    @staticmethod
    def _is_cached(conv_runtime: ConversationRuntime, message: ISACMessage) -> bool:
        """消息是否已在会话缓存里 (优先 msg_id, 无 id 时退回对象身份)。"""
        if message.msg_id:
            return any(cached.msg_id == message.msg_id for cached in conv_runtime.message_cache)
        return any(cached is message for cached in conv_runtime.message_cache)

    def _build_agent_context(
        self,
        instance: AgentInstance,
        message: ISACMessage,
        session: Session,
        user_profile: UserProfile | None,
        progress_sender: Callable[[str, ProgressEvent], Awaitable[None]] | None,
        conv_runtime: ConversationRuntime | None,
    ) -> Any:
        """构造本轮 AgentContext (进度报告 + 拟人化运行时句柄注入)。"""
        from isac.core.types import AgentContext

        reporter = self._get_or_create_progress_reporter(instance, session.session_id, progress_sender)
        progress_services: dict[str, Any] = {"task_id": uuid.uuid4().hex, "agent_id": instance.agent_id}
        if reporter is not None:
            progress_services["progress_slow_tool_threshold_seconds"] = reporter.policy.slow_tool_threshold_seconds
            progress_services["progress_report_before_slow_tool"] = reporter.policy.report_before_slow_tool
        if conv_runtime is not None:
            # P1(L4): loop 经 services 读 interrupt_state.superseded 抑制被打断的旧回复
            progress_services["conversation_runtime"] = conv_runtime
        return AgentContext(
            session=session,
            user_profile=user_profile,
            current_message=message,
            services=progress_services,
            report_progress=reporter.report if reporter is not None else None,
        )

    @staticmethod
    async def _run_loop_with_conversation(
        instance: AgentInstance,
        conv_runtime: ConversationRuntime | None,
        messages: builtins.list[dict],
        agent_context: Any,
    ) -> Any:
        """P1(L4): THINKING 状态包裹 Loop 执行 —— 锁外 notify_incoming 看到该状态即请求打断。"""
        if conv_runtime is not None:
            conv_runtime.transition_to(ConversationState.THINKING)
        try:
            return await instance.loop.run(messages, agent_context)
        finally:
            if conv_runtime is not None and conv_runtime.state is ConversationState.THINKING:
                conv_runtime.transition_to(ConversationState.IDLE)

    async def _try_command(
        self,
        instance: AgentInstance,
        message: ISACMessage,
        session: Session,
        user_profile: UserProfile | None,
    ) -> str | None:
        """E4: 尝试把消息作为 /命令 执行; 非命令/未命中返回 None。

        命令通过 context.services 访问 Agent 子系统: gating (focus/mute) /
        agent_manager (/agents 列表) / session_mgr (mute 状态); 所有 service
        字段按 Agent 级绑定, 避免命令跨 Agent 误用 (CODE_REVIEW_REPORT.md #10)。
        """
        if instance.commands is None:
            return None
        from isac.core.types import AgentContext

        agent_context_for_cmd = AgentContext(
            session=session,
            user_profile=user_profile,
            current_message=message,
            services={
                "gating": instance.gating,
                "agent_manager": self,
                "session_mgr": self._services.get("session_mgr"),
                "bus": instance.services.get("bus") or self._services.get("bus"),
                "agent_id": instance.agent_id,
            },
        )
        return await instance.commands.try_execute(message, agent_context_for_cmd)

    def _build_gating_context(
        self,
        instance: AgentInstance,
        pending: builtins.list[ISACMessage],
        session: Session,
        user_profile: UserProfile | None,
        turn_scheduler: Any,
        conv_runtime: ConversationRuntime | None,
    ) -> Any:
        """构造门控上下文; has_at/has_mention 在交给门控前填充。

        has_mention 判定: 消息文本中出现当前 Agent 的 display_name (不含 @)。
        MVP-Fix: 接收**整个 burst** 而非末条 —— has_at/has_mention 取并集, 否则
        "先 @我 再补一句" 这种突发里的点名信号会被末条覆盖掉, 整个突发不回复。
        current_message 仍取末条 (最新语境), pending_count = 本批消息数。
        """
        from isac.core.types import GatingContext

        current = pending[-1]
        display_name = instance.config.display_name
        mention_names = [display_name] if display_name else []
        bot_id = self._services.get("global_config", {}).get("bot_id", "")

        def _has_at(msg: ISACMessage) -> bool:
            return msg.has_at(bot_id) if bot_id else any(seg.type == "at" for seg in msg.segments)

        return GatingContext(
            session=session,
            user_profile=user_profile,
            current_message=current,
            is_private=current.group_id is None,
            has_at=any(_has_at(m) for m in pending),
            has_mention=any(m.has_mention(mention_names) for m in pending),
            pending_count=max(1, len(pending)),
            effective_frequency=turn_scheduler.effective_frequency(),
            recent_self_replies=turn_scheduler.recent_self_replies,
            recent_window_messages=turn_scheduler.recent_window_messages,
        )

    @staticmethod
    def _drain_pending(
        conv_runtime: ConversationRuntime | None, message: ISACMessage
    ) -> builtins.list[ISACMessage]:
        """MVP-Fix: 取出本回合要处理的消息列表 (门控与 Loop 共用同一批)。

        conversation 关闭时就是当前这条; 启用时 drain 缓存里所有未处理消息。
        **返回空列表表示本条已被前一回合合并处理, 调用方应弃权** —— 此前这里
        回退成"用本条内容再跑一轮", 导致突发消息的末条被重复回复。
        """
        if conv_runtime is None:
            return [message]
        drained = conv_runtime.drain_new_messages()
        if len(drained) > 1:
            logger.debug("debounce 合并消息", merged=len(drained))
        return drained

    @staticmethod
    def _merge_pending_content(pending: builtins.list[ISACMessage]) -> str:
        """把本回合的消息合并为一轮 user 输入 (>1 条时带说话人前缀分行)。"""
        if len(pending) == 1:
            return pending[0].content
        return "\n".join(f"{m.user_name or m.user_id}: {m.content}" for m in pending)

    def _conversation_debounce_seconds(self, instance: AgentInstance) -> float:
        """P1: 读 debounce 静默窗口秒数 (全局 conversation 节 ∪ Agent 级覆盖)。"""
        merged = {
            **(self._services.get("global_config", {}).get("conversation", {}) or {}),
            **(instance.config.conversation or {}),
        }
        try:
            return max(0.0, float(merged.get("debounce_seconds", 0.0) or 0.0))
        except (TypeError, ValueError):
            return 0.0

    async def notify_incoming(self, agent_id: str, session_id: str, message: ISACMessage) -> None:
        """P1: 锁外拟人化信号入口 (P0 dispatcher 在获取会话锁**之前**调用)。

        必须在锁外: 会话锁被正在 thinking 的上一条消息持有时, 新消息的信号才能
        穿透 —— ① 缓存进 message_cache (debounce 合并的输入); ② 若该会话在
        WAITING, 以 MESSAGE 原因唤醒 wait 工具; ③ 若在 THINKING, 请求打断
        (loop 读 superseded 抑制旧回复)。conversation 关闭时零行为变化。
        """
        if not self._conversation_enabled():
            return
        instance = self._agents.get(agent_id)
        if instance is None or instance.status != "running":
            return
        registry = instance.services.get("conversation_registry")
        if registry is None:
            return
        runtime = registry.get(agent_id, session_id)
        runtime.register_message(message)
        runtime.notify_new_message()
        if runtime.state is ConversationState.THINKING:
            runtime.request_interrupt(reason=f"新消息: {message.content[:50]}")

    async def _on_proactive_wake(self, task: ProactiveTask) -> None:
        """P1(L3): 主动任务唤醒回调 —— 经会话锁发起一次强制话轮并把回复发回原 Channel。

        会话不存在 (重启后内存会话丢失/已过期) 时跳过: 没有会话上下文不主动发言。
        该会话在 WAITING 时只以 PROACTIVE 原因唤醒 wait 工具 (由等待中的那轮接管),
        不再额外发起话轮。
        """
        instance = self._agents.get(task.agent_id)
        if instance is None or instance.status != "running":
            return
        session_mgr = self._services.get("session_mgr")
        session = await session_mgr.get(task.session_id) if session_mgr is not None else None
        if session is None:
            logger.info("主动任务的会话不存在, 跳过", task_id=task.task_id, session_id=task.session_id)
            return
        registry = instance.services.get("conversation_registry")
        runtime = registry.get(task.agent_id, session.session_id) if registry is not None else None
        if runtime is not None and runtime.state is ConversationState.WAITING:
            runtime.resolve_wait(WaitEndReason.PROACTIVE)
            return
        await self._run_forced_turn(instance, session, runtime, task)

    async def _run_forced_turn(
        self,
        instance: AgentInstance,
        session: Session,
        runtime: ConversationRuntime | None,
        task: ProactiveTask,
    ) -> None:
        """在会话锁内执行强制话轮: 合成任务上下文 → Loop → 经 Channel 发送回复。

        MVP-Fix: 锁的获取/释放改为严格配对的 `acquired` 标志。此前用
        `lock.locked()` 判定是否释放 —— 会话锁是**共享对象**, 若本协程在
        `await lock.acquire()` 处被取消 (scheduler.stop 取消调度循环时会传播到
        这里), finally 看到 `locked()` 为真 (那是并发消息任务持有的) 就会释放
        别人的锁, 单会话串行被破坏 (两条消息同时进入 Loop)。
        """
        import time as _time

        lock_mgr = self._services.get("session_lock")
        lock_key = f"{session.platform}:{session.user_id or 'unknown'}:{session.group_id or 'private'}"
        lock = await lock_mgr.acquire(lock_key) if lock_mgr is not None else None
        acquired = False
        try:
            if lock is not None:
                await lock.acquire()
                acquired = True
            if runtime is not None:
                runtime.forced_turn = ForcedTurnState(
                    source="proactive", reason=task.reason, created_at=_time.time()
                )
                runtime.transition_to(ConversationState.THINKING)
            from isac.channel.model import ISACMessage as _ISACMessage
            from isac.core.types import AgentContext

            # L3: 主动发言必带 source/intent/reason —— 经合成用户消息注入本轮上下文
            content = (
                f"[主动任务] 来源: {task.source}; 意图: {task.intent}; 原因: {task.reason}。"
                "请据此主动向用户发起一条自然、简短的消息。"
            )
            synthetic = _ISACMessage(
                msg_id=f"proactive-{task.task_id}",
                platform=session.platform,
                timestamp=int(_time.time()),
                user_id=session.user_id,
                user_name="",
                group_id=session.group_id,
                session_id=session.session_id,
                content=content,
            )
            agent_context = AgentContext(
                session=session,
                user_profile=None,
                current_message=synthetic,
                services={"task_id": uuid.uuid4().hex, "agent_id": instance.agent_id},
            )
            result = await instance.loop.run([{"role": "user", "content": content}], agent_context)
            if result.content:
                instance.gating.get_turn_scheduler(session.session_id).record_reply()
                await self._send_proactive_reply(instance, session, result.content)
        except Exception:  # noqa: BLE001
            logger.error("强制话轮执行异常", task_id=task.task_id, exc_info=True)
        finally:
            if runtime is not None:
                runtime.forced_turn = None
                if runtime.state is ConversationState.THINKING:
                    runtime.transition_to(ConversationState.IDLE)
            # 只释放**本协程真正获取到**的锁 (acquired 标志), 不看共享锁的
            # locked() 状态 —— 否则取消场景下会释放并发消息持有的同一把锁。
            if lock is not None and acquired:
                lock.release()
            if lock_mgr is not None:
                lock_mgr.release(lock_key)

    async def _send_proactive_reply(self, instance: AgentInstance, session: Session, content: str) -> None:
        """把主动话轮的回复经原 Channel 发送 (platform_session_id 保证 WebChat 可达)。"""
        from isac.channel.model import ISACMessage as _ISACMessage

        channel_registry = self._services.get("channel_registry")
        adapter = channel_registry.get(session.platform) if channel_registry is not None else None
        if adapter is None:
            logger.warning("主动消息无可用适配器, 丢弃", platform=session.platform)
            return
        reply = _ISACMessage(
            msg_id="",
            platform=session.platform,
            timestamp=0,
            user_id=session.user_id,
            user_name="",
            group_id=session.group_id,
            session_id=session.platform_session_id or session.session_id,
            content=content,
        )
        sent = await adapter.send(reply)
        logger.info("主动消息已发送" if sent else "主动消息发送失败", platform=session.platform)

    # ── 记忆写入回路 (Q1) ───────────────────────────────────

    async def drain_background_tasks(self, timeout_seconds: float = 15.0) -> None:
        """MVP-Fix: 等待在途的后台记忆写入任务完成 (优雅关闭时调用)。

        `_schedule_memory_write` 派生的任务不在 dispatcher 的 inflight 集合里 ——
        消息任务在产出回复后立即返回并离开 inflight, 记忆写入还在跑。关闭链此前
        只 drain dispatcher, 导致最后若干轮的 episodic 记忆 / 画像自增 / 会话快照
        在 `asyncio.run` 收尾取消任务时静默丢失 (正是"越聊越熟"要落的数据)。
        """
        pending = [t for t in self._memory_tasks if not t.done()]
        if not pending:
            return
        logger.info("等待在途记忆写入完成", count=len(pending))
        _done, still_pending = await asyncio.wait(pending, timeout=timeout_seconds)
        if still_pending:
            logger.warning("记忆写入未在超时内完成, 继续关闭", count=len(still_pending))

    def _schedule_memory_write(
        self,
        instance: AgentInstance,
        message: ISACMessage,
        session: Session,
        user_profile: UserProfile | None,
        reply: str,
        user_content: str | None = None,
    ) -> None:
        """Q1: 把本轮对话写入记忆 (后台任务, 失败降级不影响回复)。

        这是差距复核发现的 MVP 最关键缺口: 检索/注入/治理整条读链路就绪, 但生产
        从未调用 store_episode, 记忆恒为空。写入放后台任务是为了不给回复路径增加
        延迟 (配置 embedding 时 store_episode 内含一次向量化 API 调用)。
        user_content 缺省时用 message.content (直调 handle_message 的旧调用方)。
        """
        task = asyncio.create_task(
            self._write_memory(instance, message, session, user_profile, reply, user_content),
            name=f"memory-write-{session.session_id}",
        )
        self._memory_tasks.add(task)
        task.add_done_callback(self._memory_tasks.discard)

    async def _write_memory(
        self,
        instance: AgentInstance,
        message: ISACMessage,
        session: Session,
        user_profile: UserProfile | None,
        reply: str,
        user_content: str | None = None,
    ) -> None:
        """写入一轮对话的 episodic 记忆 + 更新人物画像 (SPECIFICATION 5.1: 失败降级)。"""
        try:
            user_name = message.user_name or message.user_id
            display_name = instance.config.display_name or instance.agent_id
            # 存整轮对话 (用户话 + 回复): BM25/向量召回都能命中双方内容,
            # 注入时也能还原"谁说了什么"。合并回合存的是**整个 burst**
            # (user_content, 已带说话人前缀), 与 Agent 实际看到的输入一致。
            said = user_content if user_content is not None else message.content
            content = (
                f"{said}\n{display_name}: {reply}"
                if user_content is not None and len(said.splitlines()) > 1
                else f"{user_name}: {said}\n{display_name}: {reply}"
            )
            await instance.memory.store_episode(
                content=content,
                session_id=session.session_id,
                user_id=message.user_id,
                group_id=message.group_id or "",
                metadata={"importance": 0.5},
            )
            await self._update_person_profile(instance, message, user_profile)
            # P1(L5): conversation 启用时顺带保存会话拟人状态快照 (启动恢复的数据源)
            await self._save_conversation_snapshot(instance, session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("记忆写入失败, 已忽略 (不影响回复)", error=str(exc))

    @staticmethod
    async def _save_conversation_snapshot(instance: AgentInstance, session: Session) -> None:
        """P1(L5): 回复后保存会话快照 (conversation_state_store 未注入时零行为变化)。

        快照键用**重启稳定**的会话键 (platform:group/user) 而非内部 sess_* id ——
        SessionManager 是内存实现, session_id 每次重启都会重新生成, 用它作键的
        快照重启后永远无法命中; RecoveryInjector 按同一公式重建键匹配。
        """
        store = instance.services.get("conversation_state_store")
        if store is None:
            return
        registry = instance.services.get("conversation_registry")
        runtime = (
            registry.get(instance.agent_id, session.session_id) if registry is not None else None
        )
        stable_key = (
            f"{session.platform}:group:{session.group_id}"
            if session.group_id
            else f"{session.platform}:user:{session.user_id}"
        )
        snapshot = ConversationSnapshot(
            agent_id=instance.agent_id,
            session_id=stable_key,
            state="idle",
            recent_message_ids=[m.msg_id for m in (runtime.message_cache[-5:] if runtime else [])],
        )
        await asyncio.to_thread(store.save, snapshot)

    async def _update_person_profile(
        self,
        instance: AgentInstance,
        message: ISACMessage,
        user_profile: UserProfile | None,
    ) -> None:
        """Q1: 每次互动更新人物画像 (interaction_count/relationship_depth/last_seen)。

        person_id 与读侧 (PersonProfileInjector / query_person_profile 工具) 保持
        同一口径: 优先 UserMapper master_id (Q1 起 SQLite 持久化, 跨重启稳定),
        无 user_profile 时退化用平台 user_id (与注入器的 session.user_id 兜底一致)。
        agent 键用 instance.agent_id (读侧用 session.agent_id, 二者相同)。
        画像文本的 LLM 归纳留 MemoryConsolidator (MVP 之后), 本回路只做启发式累积。
        """
        metadata_store = getattr(instance.memory, "metadata", None)
        if metadata_store is None:
            return  # NoOpMemoryPipeline / memory 未启用
        from isac.utils.helpers import unix_now

        person_id = (getattr(user_profile, "user_id", "") or message.user_id or "").strip()
        if not person_id:
            return
        existing = await metadata_store.get_person_profile(instance.agent_id, person_id) or {}
        now = unix_now()
        await metadata_store.upsert_person_profile(
            instance.agent_id,
            {
                "person_id": person_id,
                "name": message.user_name or existing.get("name") or message.user_id,
                "profile_text": existing.get("profile_text", "") or "",
                "traits": existing.get("traits", []) or [],
                "relationship_depth": min(
                    1.0, float(existing.get("relationship_depth", 0.0) or 0.0) + RELATIONSHIP_DEPTH_STEP
                ),
                "interaction_count": int(existing.get("interaction_count", 0) or 0) + 1,
                "first_seen": existing.get("first_seen") or now,
                "last_seen": now,
            },
        )

    # ── 路由信息 (注入 MessageRouter 的 agents_provider) ────

    def routing_infos(self) -> builtins.list[AgentConfig]:
        """返回所有运行中 Agent 的路由信息 (agent_id + trigger_words)。"""
        return [a.config for a in self._agents.values() if a.status == "running"]

    # ── P2 Mesh: 角色 / 仲裁分数 / 旁听 ──────────────────────

    def mesh_roles(self) -> dict[str, str]:
        """P2: 运行中 Agent 的 mesh 角色映射 (agent_id → observer|candidate|primary)。

        只返回显式配置了非空 mesh_role 的 Agent; 全空 = 单主路由 (零行为变化)。
        """
        return {
            a.agent_id: a.config.mesh_role
            for a in self._agents.values()
            if a.status == "running" and a.config.mesh_role
        }

    async def gating_score(
        self, agent_id: str, message: ISACMessage, session: Session, user_profile: UserProfile | None
    ) -> float:
        """P2: 某 Agent 对这条消息的回复必要性评分 (候选仲裁的依据)。

        复用门控的 ReplyNecessityJudge (纯启发式, 不调 LLM), 归一化到 0~1。
        Agent 不存在/未运行/评分异常时返回 0.0 (保守: 不参与切换)。
        """
        instance = self._agents.get(agent_id)
        if instance is None or instance.status != "running":
            return 0.0
        try:
            turn_scheduler = instance.gating.get_turn_scheduler(session.session_id)
            gating_context = self._build_gating_context(
                instance, [message], session, user_profile, turn_scheduler, None
            )
            raw = await instance.gating.reply_necessity.score([message], gating_context)
            return max(0.0, min(1.0, float(raw) / 100.0))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Mesh 候选评分失败, 记 0", agent_id=agent_id, error=str(exc))
            return 0.0

    async def observe_message(
        self,
        agent_id: str,
        message: ISACMessage,
        session: Session,
        user_profile: UserProfile | None,
    ) -> None:
        """P2: 旁听 —— observer Agent 只把消息写进自己的记忆, 不回复、不占用话轮。

        与 handle_message 的区别: 不过门控、不跑 Loop、不发回复; 只写 episodic
        记忆 (让 observer 具备"听过"的上下文, 供后续被 ask/仲裁选中时使用)。
        """
        instance = self._agents.get(agent_id)
        if instance is None or instance.status != "running":
            return
        with bind_log_context(trace_id=uuid.uuid4().hex, session_id=session.session_id, agent_id=agent_id):
            try:
                speaker = message.user_name or message.user_id
                await instance.memory.store_episode(
                    content=f"{speaker}: {message.content}",
                    session_id=session.session_id,
                    user_id=message.user_id,
                    group_id=message.group_id or "",
                    metadata={"importance": 0.3, "observed": True},
                )
                await self._update_person_profile(instance, message, user_profile)
                logger.debug("旁听消息已入记忆", agent_id=agent_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("旁听写入失败, 已忽略", agent_id=agent_id, error=str(exc))

    # ── 内部 ────────────────────────────────────────────────

    def _conversation_enabled(self) -> bool:
        """L1: 是否启用会话级拟人运行时 (默认关闭 → 主链路零行为变化)。"""
        return bool(
            self._services.get("global_config", {}).get("conversation", {}).get("enabled", False)
        )

    def _require(self, agent_id: str) -> AgentInstance:
        instance = self._agents.get(agent_id)
        if instance is None:
            raise AgentNotFoundError(f"Agent 不存在: {agent_id}")
        return instance

    def _inc_metric(self, name: str) -> None:
        metrics = self._services.get("metrics")
        if metrics is not None:
            metrics.counter(name).inc()

    def _update_active_gauge(self) -> None:
        """重新统计 status=running 的 Agent 数并更新 isac_agents_active。"""
        metrics = self._services.get("metrics")
        if metrics is None:
            return
        active = sum(1 for instance in self._agents.values() if instance.status == "running")
        metrics.gauge("isac_agents_active").set(active)

    def _get_or_create_progress_reporter(
        self,
        instance: AgentInstance,
        session_id: str,
        sender: Callable[[str, ProgressEvent], Awaitable[None]] | None,
    ) -> ProgressReporter | None:
        """D9: 按 session 复用 ProgressReporter (使 min_interval_seconds 频控跨消息生效)。

        未注入 progress_reporter_factory 时返回 None (旧测试/未组装该服务的场景),
        主链路保持零行为变化。sender 每次调用都重新绑定, 因为同一 session 后续消息
        可能来自不同的 Channel 连接。
        """
        factory = instance.services.get("progress_reporter_factory")
        if factory is None:
            return None
        reporter = instance.progress_reporters.get(session_id)
        if reporter is None:
            if len(instance.progress_reporters) >= MAX_PROGRESS_REPORTERS_PER_AGENT:
                oldest_session_id = next(iter(instance.progress_reporters))
                del instance.progress_reporters[oldest_session_id]
            reporter = factory(session_id, sender=sender)
            instance.progress_reporters[session_id] = reporter
        else:
            reporter.rebind_sender(sender)
        return reporter


async def ensure_default_agent(manager: AgentManager, global_config: dict) -> AgentInstance:
    """向后兼容: 无 data/agents/ 时创建默认 Agent (单 Agent 模式)。"""
    existing = await manager.get(DEFAULT_AGENT_ID)
    if existing is not None:
        return existing
    instance = await manager.create(AgentConfig(agent_id=DEFAULT_AGENT_ID, display_name="ISAC"))
    await manager.start(DEFAULT_AGENT_ID)
    logger.info("已创建默认 Agent (单 Agent 兼容模式)", agent_id=DEFAULT_AGENT_ID)
    return instance


async def load_persisted_agents(manager: AgentManager, agents_dir: str) -> dict[str, str]:
    """重启时从 data/agents/*/config.jsonc 恢复所有 enabled=true 的 Agent。

    对每个加载到的 AgentConfig: create() 成功后, 若 enabled=true 自动 start()。
    单个 Agent 恢复失败不阻塞其他 Agent, 错误记日志并跳过
    (CODE_REVIEW_REPORT.md #2)。

    返回 {agent_id: "running"/"stopped"/"failed: <error>"} 报告。
    """
    from isac.runtime.config import load_agent_config

    root = Path(agents_dir)
    # 用 to_thread 包装 blocking Path 操作, 避免在 event loop 里直接执行 (ruff ASYNC240)。
    config_paths = await asyncio.to_thread(_scan_agent_configs, root)
    if not config_paths:
        return {}
    report: dict[str, str] = {}
    for config_path in config_paths:
        try:
            agent_config = await asyncio.to_thread(load_agent_config, config_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Agent 配置加载失败, 跳过", path=str(config_path), error=str(exc))
            report[config_path.parent.name] = f"failed: {exc}"
            continue
        if agent_config.agent_id in await manager.list_ids():
            report[agent_config.agent_id] = "already-loaded"
            continue
        try:
            await manager.create(agent_config)
            if agent_config.enabled:
                await manager.start(agent_config.agent_id)
                report[agent_config.agent_id] = "running"
            else:
                report[agent_config.agent_id] = "stopped"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Agent 恢复失败, 跳过", agent_id=agent_config.agent_id, error=str(exc))
            report[agent_config.agent_id] = f"failed: {exc}"
    return report


def _scan_agent_configs(root: Path) -> list[Path]:
    """同步扫描 agents_dir 下所有 config.jsonc, 按目录名排序。

    拆成同步 helper 是为了让 async 调用方用 asyncio.to_thread 包装, 不在 event loop 里
    执行 blocking Path.glob (ruff ASYNC240)。
    """
    if not root.exists():
        return []
    return sorted(root.glob("*/config.jsonc"))
