"""MessageRouter: Channel 连接与 Agent 解耦的关键 (ARCHITECTURE.md 3.2)。

路由优先级 (先匹配先生效):
1. 自定义 Router Hook (预留, Native SDK register_router_hook)
2. 显式绑定: (platform, group_id/user_id) → agent_id
3. 触发词: 消息以某 Agent 的 trigger_word 开头 (匹配后剥离)
4. 默认 Agent: 该 platform 配置 default_agent_id (无需触发词)
5. 无匹配 → None (DROP + 记录日志)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from isac.channel.model import ISACMessage
from isac.router.types import AgentsProvider, RoutingDecision, RoutingRules
from isac.utils.logger import get_logger

logger = get_logger(__name__)

RouterHook = Callable[[ISACMessage], Awaitable[RoutingDecision | None]]


class MessageRouter:
    """消息路由器。规则可热更新 (控制面写入 data/routing.jsonc)。"""

    def __init__(self, rules: RoutingRules, agents_provider: AgentsProvider):
        """
        Args:
            rules: 初始路由规则
            agents_provider: 返回所有可路由 Agent 路由信息的回调 (由 runtime 注入)
        """
        self._rules = rules
        self._agents_provider = agents_provider
        self._router_hooks: list[RouterHook] = []

    # ── 规则管理 (控制面调用) ──────────────────────────────

    def set_rules(self, rules: RoutingRules) -> None:
        """热更新路由规则。"""
        self._rules = rules
        logger.info("路由规则已热更新", bindings=len(rules.bindings), defaults=len(rules.default_agents))

    def get_rules(self) -> RoutingRules:
        return self._rules

    def register_router_hook(self, fn: RouterHook) -> None:
        """预留: 自定义路由函数 (Native SDK)，在显式绑定之前执行。"""
        self._router_hooks.append(fn)

    # ── 路由 ────────────────────────────────────────────────

    async def route(self, message: ISACMessage) -> RoutingDecision | None:
        """决定消息归属。返回 None 表示 DROP。"""
        # 0. 自定义 Router Hook (预留接口)
        for hook in self._router_hooks:
            try:
                decision = await hook(message)
            except Exception as exc:
                logger.error("Router Hook 异常，已跳过", error=str(exc), exc_info=True)
                continue
            if decision is not None:
                return decision

        # 1. 显式绑定
        decision = self._match_binding(message)
        if decision:
            return decision

        # 2. 触发词
        decision = self._match_trigger_word(message)
        if decision:
            return decision

        # 3. 默认 Agent
        default_agent = self._rules.default_agents.get(message.platform)
        if default_agent:
            return RoutingDecision(agent_id=default_agent, matched_by="default", content=message.content)

        # 4. DROP
        logger.debug(
            "路由无匹配，消息丢弃",
            platform=message.platform,
            group_id=message.group_id,
            user_id=message.user_id,
        )
        return None

    def _match_binding(self, message: ISACMessage) -> RoutingDecision | None:
        for binding in self._rules.bindings:
            if binding.platform != message.platform:
                continue
            if binding.group_id is not None and binding.group_id != message.group_id:
                continue
            if binding.user_id is not None and binding.user_id != message.user_id:
                continue
            return RoutingDecision(agent_id=binding.agent_id, matched_by="binding", content=message.content)
        return None

    def _match_trigger_word(self, message: ISACMessage) -> RoutingDecision | None:
        content = message.content.strip()
        for agent in self._agents_provider():
            for word in agent.trigger_words:
                if word and content.startswith(word):
                    stripped = content[len(word):].strip()
                    return RoutingDecision(agent_id=agent.agent_id, matched_by="trigger_word", content=stripped)
        return None
