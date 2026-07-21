"""Agent 组装器: 按 AgentConfig 组装独立子系统 (ARCHITECTURE.md 3.1)。

组装顺序遵循 DEVELOP.md 1.2 导入规则；共享服务 (ProviderManager 等) 注入。
"""

from __future__ import annotations

from typing import Any

from isac.agent.hooks import AgentHooks
from isac.agent.injectors.base_identity import BaseIdentityInjector
from isac.agent.injectors.tools_available import ToolsAvailableInjector
from isac.agent.loop import ISACAgentLoop
from isac.agent.prompt_builder import SystemPromptBuilder
from isac.agent.tools.base import ToolPermission
from isac.agent.tools.registry import ToolRegistry
from isac.gating.system import GatingSystem
from isac.persona.manager import PersonaManager
from isac.runtime.config import AgentConfig
from isac.runtime.instance import AgentInstance
from isac.utils.logger import get_logger

logger = get_logger(__name__)


async def assemble_agent(config: AgentConfig, services: dict[str, Any]) -> AgentInstance:
    """按配置组装一个 AgentInstance。

    Args:
        config: Agent 独立配置
        services: 共享服务 {"provider_manager", "memory_factory", "global_config", ...}

    TODO(Day 32-33):
    - MemoryRetrievalPipeline 经 memory_factory(namespace=config.effective_memory_namespace) 创建
    - 注册人格注入器 (attention_drift/expression_style/mood/skill_selector)
    - 注册记忆注入器 (heuristic/person_profile/jargon/mid_term)
    - 注册内置工具 (social) 与 BehaviorLearner/TurnScheduler 的 Hooks
    - AgentConfig.llm 非空时创建独立 Provider
    """
    global_config: dict = services.get("global_config", {})

    gating = GatingSystem()  # TODO(Day 32): 应用 config.gating 覆盖项

    prompt_builder = SystemPromptBuilder()
    prompt_builder.register(BaseIdentityInjector())

    hooks = AgentHooks()
    permission = ToolPermission(config.tools_policy)
    tools = ToolRegistry(permission)
    prompt_builder.register(ToolsAvailableInjector(tools))

    provider_manager = services["provider_manager"]
    llm = provider_manager.for_agent(config)
    loop = ISACAgentLoop(
        llm=llm,
        prompt_builder=prompt_builder,
        hooks=hooks,
        tools=tools,
        provider_manager=provider_manager,
    )

    memory = services["memory_factory"](config.effective_memory_namespace)
    persona = PersonaManager(global_config.get("persona", {}), config.persona)

    logger.info("Agent 组装完成", agent_id=config.agent_id, namespace=config.effective_memory_namespace)
    return AgentInstance(
        agent_id=config.agent_id,
        config=config,
        gating=gating,
        prompt_builder=prompt_builder,
        hooks=hooks,
        loop=loop,
        memory=memory,
        persona=persona,
        tools=tools,
    )
