"""AgentManager: Agent 生命周期管理 (ARCHITECTURE.md 3.1 / SPECIFICATION.md 2.8)。

所有公开方法同时暴露给控制面 (Admin API / MCP Server)，control/ 不复制业务逻辑。
"""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, Any

from isac.core.constants import DEFAULT_AGENT_ID
from isac.core.exceptions import AgentNotFoundError
from isac.gating.types import GateKind
from isac.runtime.assembly import assemble_agent
from isac.runtime.config import AgentConfig
from isac.runtime.instance import AgentInstance
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.channel.model import ISACMessage
    from isac.gateway.models import Session, UserProfile

logger = get_logger(__name__)


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

    # ── 生命周期 (控制面暴露) ──────────────────────────────

    async def create(self, config: AgentConfig) -> AgentInstance:
        """创建并组装 Agent (默认 stopped，需 start 后才处理消息)。"""
        if config.agent_id in self._agents:
            raise ValueError(f"Agent 已存在: {config.agent_id}")
        instance = await assemble_agent(config, self._services)
        self._agents[config.agent_id] = instance
        self._inc_metric("isac_agent_creates_total")
        logger.info("Agent 已创建", agent_id=config.agent_id)
        return instance

    async def start(self, agent_id: str) -> None:
        instance = self._require(agent_id)
        instance.status = "running"
        self._inc_metric("isac_agent_starts_total")
        self._update_active_gauge()
        logger.info("Agent 已启动", agent_id=agent_id)

    async def stop(self, agent_id: str) -> None:
        instance = self._require(agent_id)
        instance.status = "stopped"
        self._inc_metric("isac_agent_stops_total")
        self._update_active_gauge()
        logger.info("Agent 已停止", agent_id=agent_id)

    async def destroy(self, agent_id: str, *, keep_memory: bool = True) -> None:
        """销毁 Agent。keep_memory=True 时保留记忆数据。"""
        self._require(agent_id)
        del self._agents[agent_id]
        self._update_active_gauge()
        # TODO: keep_memory=False 时清理 data/agents/<id>/memory/
        logger.info("Agent 已销毁", agent_id=agent_id, keep_memory=keep_memory)

    async def get(self, agent_id: str) -> AgentInstance | None:
        return self._agents.get(agent_id)

    async def list(self) -> list[AgentInstance]:
        return list(self._agents.values())

    async def reload_config(self, agent_id: str, config: AgentConfig) -> None:
        """热更新配置 (重建子系统中受配置影响的部分)。

        TODO: 差量更新 gating/persona/权限, 避免整实例重建。
        """
        was_running = self._require(agent_id).status == "running"
        instance = await assemble_agent(config, self._services)
        instance.status = "running" if was_running else "stopped"
        self._agents[agent_id] = instance
        logger.info("Agent 配置已重载", agent_id=agent_id)

    # ── 消息处理入口 (由 MessageRouter 经依赖注入调用) ─────

    async def handle_message(
        self,
        agent_id: str,
        message: ISACMessage,
        session: Session,
        user_profile: UserProfile | None,
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

        # 每条到达消息都累加注入器的新消息计数 (按 session 隔离, 支撑 max_new_messages 频率控制)。
        instance.prompt_builder.notify_new_message(session.session_id)

        # 同步记录到该 session 独立的 TurnScheduler 滑窗，供 effective_frequency / 存在感惩罚计算。
        turn_scheduler = instance.gating.get_turn_scheduler(session.session_id)
        turn_scheduler.record_window_message()

        from isac.core.types import AgentContext, GatingContext  # 避免模块级循环

        # E4: 命令拦截 (在门控前)。/cmd 是用户显式发起, 跳过门控。
        if instance.commands is not None and message.content.startswith("/"):
            agent_context_for_cmd = AgentContext(
                session=session,
                user_profile=user_profile,
                current_message=message,
            )
            cmd_result = await instance.commands.try_execute(message, agent_context_for_cmd)
            if cmd_result is not None:
                turn_scheduler.record_reply()
                instance.gating.get_idle_backoff(session.session_id).record_reply()
                return cmd_result

        # 构造门控上下文；has_at / has_mention 在交给门控前填充。
        # has_mention 判定：消息文本中出现当前 Agent 的 display_name（不含 @）。
        display_name = instance.config.display_name
        mention_names = [display_name] if display_name else []
        bot_id = self._services.get("global_config", {}).get("bot_id", "")
        has_at = message.has_at(bot_id) if bot_id else any(seg.type == "at" for seg in message.segments)

        gating_context = GatingContext(
            session=session,
            user_profile=user_profile,
            current_message=message,
            is_private=message.group_id is None,
            has_at=has_at,
            has_mention=message.has_mention(mention_names),
            pending_count=1,  # 当前实现: 单条即时处理, 积压恒为 1
            effective_frequency=turn_scheduler.effective_frequency(),
            recent_self_replies=turn_scheduler.recent_self_replies,
            recent_window_messages=turn_scheduler.recent_window_messages,
        )
        decision = await instance.gating.evaluate([message], gating_context)
        if decision.kind != GateKind.TRIGGER:
            logger.debug("门控未触发", agent_id=agent_id, kind=decision.kind.value)
            return None

        agent_context = AgentContext(
            session=session,
            user_profile=user_profile,
            current_message=message,
        )
        messages = [{"role": "user", "content": message.content}]
        result = await instance.loop.run(messages, agent_context)
        if result.content:
            # 话轮调度: 记录本轮回复, 更新滑窗频率与存在感数据。
            turn_scheduler.record_reply()
            instance.gating.get_idle_backoff(session.session_id).record_reply()
        return result.content or None

    # ── 路由信息 (注入 MessageRouter 的 agents_provider) ────

    def routing_infos(self) -> builtins.list[AgentConfig]:
        """返回所有运行中 Agent 的路由信息 (agent_id + trigger_words)。"""
        return [a.config for a in self._agents.values() if a.status == "running"]

    # ── 内部 ────────────────────────────────────────────────

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


async def ensure_default_agent(manager: AgentManager, global_config: dict) -> AgentInstance:
    """向后兼容: 无 data/agents/ 时创建默认 Agent (单 Agent 模式)。"""
    existing = await manager.get(DEFAULT_AGENT_ID)
    if existing is not None:
        return existing
    instance = await manager.create(AgentConfig(agent_id=DEFAULT_AGENT_ID, display_name="ISAC"))
    await manager.start(DEFAULT_AGENT_ID)
    logger.info("已创建默认 Agent (单 Agent 兼容模式)", agent_id=DEFAULT_AGENT_ID)
    return instance
