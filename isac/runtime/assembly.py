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
from isac.agent.tools.social.ask_agent import AskAgentTool
from isac.agent.tools.social.fetch_history import FetchHistoryTool
from isac.agent.tools.social.query_memory import QueryMemoryTool
from isac.agent.tools.social.query_person_profile import QueryPersonProfileTool
from isac.agent.tools.social.send_emoji import SendEmojiTool
from isac.agent.tools.social.send_image import SendImageTool
from isac.agent.tools.social.switch_chat import SwitchChatTool
from isac.agent.tools.social.view_forward_message import ViewForwardMessageTool
from isac.agent.tools.social.wait import WaitTool
from isac.agent.tools.utility.bash import BashTool
from isac.agent.tools.utility.read_file import ReadFileTool
from isac.agent.tools.utility.task import TaskTool
from isac.agent.tools.utility.web_search import WebSearchTool
from isac.agent.tools.utility.write_file import WriteFileTool
from isac.commands.builtin.agents import AgentsCommand
from isac.commands.builtin.focus import FocusCommand
from isac.commands.builtin.mute import MuteCommand, UnmuteCommand
from isac.commands.registry import CommandRegistry
from isac.core.policy import EnableMatrix
from isac.gating.system import GatingSystem
from isac.memory.injector.heuristic import HeuristicMemoryInjector
from isac.memory.injector.jargon import JargonInjector
from isac.memory.injector.mid_term import MidTermMemoryInjector
from isac.memory.injector.person_profile import PersonProfileInjector
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

    [已完成] memory_factory / 人格注入器 / 记忆注入器 / BehaviorLearner hooks;
    待落地: attention_drift/expression_style/mood/skill_selector 注入器接入 PersonaManager,
            AgentConfig.llm 非空时创建独立 Provider, config.gating 覆盖项应用。
    """
    global_config: dict = services.get("global_config", {})

    # E4 启用矩阵: Agent ∩ Channel ∩ 全局; Channel 覆盖来自 global_config.channels
    channel_overrides: dict = {}
    for platform, platform_cfg in global_config.get("channels", {}).items():
        if isinstance(platform_cfg, dict) and "matrix" in platform_cfg:
            channel_overrides[platform] = platform_cfg["matrix"]
    enable_matrix = EnableMatrix(
        global_policy=global_config.get("policy", {}),
        channel_overrides=channel_overrides,
    )

    gating = GatingSystem()  # TODO: 应用 config.gating 覆盖项

    prompt_builder = SystemPromptBuilder()
    prompt_builder.register(BaseIdentityInjector())

    hooks = AgentHooks()
    permission = ToolPermission(config.tools_policy)
    tools = ToolRegistry(permission, enable_matrix=enable_matrix, agent_id=config.agent_id)
    # 社交类工具: 与 Channel/记忆交互, 多为 allow 策略
    tools.register(QueryMemoryTool())
    tools.register(QueryPersonProfileTool())
    tools.register(WaitTool())
    tools.register(AskAgentTool())
    tools.register(SendEmojiTool())
    tools.register(SendImageTool())
    tools.register(FetchHistoryTool())
    tools.register(SwitchChatTool())
    tools.register(ViewForwardMessageTool())
    # 实用类工具: 受 restricted 策略, 必须注入对应后端方可调用
    tools.register(BashTool())
    tools.register(ReadFileTool())
    tools.register(WriteFileTool())
    tools.register(WebSearchTool())
    tools.register(TaskTool())
    prompt_builder.register(ToolsAvailableInjector(tools))

    # E4 命令注册表: commands_allow 矩阵在 try_execute 时生效
    def _cmd_enable_check(name: str, agent_id: str, platform: str) -> bool:
        instance_agent_id = agent_id or config.agent_id
        return enable_matrix.is_command_enabled(
            name, config.commands_allow, agent_id=instance_agent_id, platform=platform
        )

    commands = CommandRegistry(enable_checker=_cmd_enable_check)
    commands.register(AgentsCommand())
    commands.register(FocusCommand())
    commands.register(MuteCommand())
    commands.register(UnmuteCommand())

    provider_manager = services["provider_manager"]
    llm = provider_manager.for_agent(config)
    memory = services["memory_factory"](config.effective_memory_namespace)
    prompt_builder.register(PersonProfileInjector(memory))
    prompt_builder.register(JargonInjector(memory))
    prompt_builder.register(HeuristicMemoryInjector(memory))
    prompt_builder.register(MidTermMemoryInjector(memory))
    agent_services = {**services, "memory": memory}
    loop = ISACAgentLoop(
        llm=llm,
        prompt_builder=prompt_builder,
        hooks=hooks,
        tools=tools,
        provider_manager=provider_manager,
        services=agent_services,
    )

    persona = PersonaManager(global_config.get("persona", {}), config.persona)
    # 注册 BehaviorLearner FINAL_RESPONSE hook, 从回复中学习用户行为模式。
    persona.register_hooks(hooks)

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
        services=agent_services,
        enable_matrix=enable_matrix,
        commands=commands,
    )
