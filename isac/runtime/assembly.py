"""Agent 组装器: 按 AgentConfig 组装独立子系统 (ARCHITECTURE.md 3.1)。

组装顺序遵循 DEVELOP.md 1.2 导入规则；共享服务 (ProviderManager 等) 注入。
"""

from __future__ import annotations

from typing import Any

from isac.agent.hooks import AgentHooks
from isac.agent.injectors.base_identity import BaseIdentityInjector
from isac.agent.injectors.interrupt import InterruptInjector
from isac.agent.injectors.model_capabilities import ModelCapabilitiesInjector
from isac.agent.injectors.recovery import RecoveryInjector
from isac.agent.injectors.tools_available import ToolsAvailableInjector
from isac.agent.loop import ISACAgentLoop
from isac.agent.prompt_builder import SystemPromptBuilder
from isac.agent.tools.base import ToolPermission
from isac.agent.tools.registry import ToolRegistry
from isac.agent.tools.social.ask_agent import AskAgentTool
from isac.agent.tools.social.fetch_history import FetchHistoryTool
from isac.agent.tools.social.handoff_conversation import HandoffConversationTool
from isac.agent.tools.social.list_available_agents import ListAvailableAgentsTool
from isac.agent.tools.social.memory_query_agent import MemoryQueryAgentTool
from isac.agent.tools.social.notify_agent import NotifyAgentTool
from isac.agent.tools.social.query_memory import QueryMemoryTool
from isac.agent.tools.social.query_person_profile import QueryPersonProfileTool
from isac.agent.tools.social.send_emoji import SendEmojiTool
from isac.agent.tools.social.send_image import SendImageTool
from isac.agent.tools.social.switch_chat import SwitchChatTool
from isac.agent.tools.social.view_forward_message import ViewForwardMessageTool
from isac.agent.tools.social.wait import WaitTool
from isac.agent.tools.subagent import (
    CancelSubagentTool,
    DelegateTaskTool,
    ListSubagentsTool,
    SubagentLogTool,
    SubagentStatusTool,
)
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
from isac.runtime.conversation import (
    ConversationRuntimeRegistry,
    ConversationStateStore,
    ProactiveScheduler,
)
from isac.runtime.instance import AgentInstance
from isac.runtime.progress import build_progress_reporter
from isac.utils.logger import get_logger

logger = get_logger(__name__)


async def _setup_conversation_runtime(
    config: AgentConfig,
    global_config: dict,
    agent_services: dict[str, Any],
    prompt_builder: SystemPromptBuilder,
) -> None:
    """P1: 拟人化会话子系统装配 (registry/开关/打断恢复注入器/调度器/状态存储)。

    - L1: 会话级运行时注册表 (每 Agent 独立, 会话间隔离); 配置为
      全局 conversation 节 ∪ Agent 级覆盖 (AgentConfig.conversation, enabled 除外)。
    - CR2-Fix-8: InterruptInjector 经 runtime_provider 闭包按 session 查询;
      enabled=False 时短路返回 None, 零行为变化。
    - P1(L3/L5): enabled=True 时构造 ProactiveScheduler (start/stop 由 AgentManager
      随 Agent 生命周期驱动) + ConversationStateStore, 并把未过期会话快照批量恢复
      进 RecoveryInjector (下一轮对话注入"刚醒来"提示)。
    """
    conv_merged = {**(global_config.get("conversation", {}) or {}), **(config.conversation or {})}
    agent_services["conversation_registry"] = ConversationRuntimeRegistry(
        max_interrupts_per_turn=max(1, int(conv_merged.get("max_interrupts_per_turn", 1) or 1))
    )
    conversation_enabled = bool(global_config.get("conversation", {}).get("enabled", False))
    agent_services["conversation_enabled"] = conversation_enabled

    def _interrupt_runtime_provider(session_id: str):  # noqa: ANN001, ANN202
        if not agent_services["conversation_enabled"]:
            return None
        return agent_services["conversation_registry"].get(config.agent_id, session_id)

    prompt_builder.register(InterruptInjector(runtime_provider=_interrupt_runtime_provider))
    recovery_injector = RecoveryInjector()
    prompt_builder.register(recovery_injector)

    if not conversation_enabled:
        return
    import asyncio as _asyncio

    proactive_cfg = conv_merged.get("proactive", {}) or {}
    agent_services["proactive_scheduler"] = ProactiveScheduler(
        min_interval_seconds=float(proactive_cfg.get("min_interval_seconds", 600) or 0),
        poll_interval_seconds=float(proactive_cfg.get("poll_interval_seconds", 1.0) or 1.0),
    )
    state_store = ConversationStateStore()
    agent_services["conversation_state_store"] = state_store
    snapshots = await _asyncio.to_thread(state_store.load_all, config.agent_id)
    for stable_key, snapshot in snapshots.items():
        recovery_injector.add_snapshot(stable_key, snapshot)
    if snapshots:
        logger.info("会话拟人状态快照已恢复", agent_id=config.agent_id, count=len(snapshots))


async def assemble_agent(config: AgentConfig, services: dict[str, Any]) -> AgentInstance:
    """按配置组装一个 AgentInstance。

    Args:
        config: Agent 独立配置
        services: 共享服务 {"provider_manager", "memory_factory", "global_config", ...}

    [已完成] memory_factory / 人格注入器 / 记忆注入器 / BehaviorLearner hooks / SubAgent 工具;
    待落地: attention_drift/expression_style/mood/skill_selector 注入器接入 PersonaManager。
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

    gating = GatingSystem(config=config.gating)

    prompt_builder = SystemPromptBuilder()
    prompt_builder.register(BaseIdentityInjector())
    # J2: 多模态能力注入器 (默认无授权媒体能力 → 注入空串, 主链路零变化)。
    # model_capabilities_allow 字段将在 J2 实现节点加入 AgentConfig; 当前经 getattr 兜底。
    _media_caps = [c for c in (getattr(config, "model_capabilities_allow", None) or []) if c != "chat"]
    prompt_builder.register(ModelCapabilitiesInjector(_media_caps))

    hooks = AgentHooks()
    # CR3-H2: 插件经 on_load 注册到进程级共享注册表 (services["plugin_agent_hooks"],
    # main._fire_plugin_on_load 构造) 的钩子, 合并进本 Agent 的私有 hooks
    # (保留 priority; 同仓读内部结构, AgentHooks._hooks 即注册表本体)。
    plugin_hooks: AgentHooks | None = services.get("plugin_agent_hooks")
    if plugin_hooks is not None:
        for point, entries in plugin_hooks._hooks.items():  # noqa: SLF001
            for priority, _seq, fn in entries:
                hooks.register(point, fn, priority=priority)
    permission = ToolPermission(config.tools_policy)
    tools = ToolRegistry(permission, enable_matrix=enable_matrix, agent_id=config.agent_id)
    # 社交类工具: 与 Channel/记忆交互, 多为 allow 策略
    tools.register(QueryMemoryTool())
    tools.register(QueryPersonProfileTool())
    tools.register(WaitTool())
    tools.register(AskAgentTool())
    # M2 Agent Mesh 协作工具: notify_agent/handoff_conversation/
    # list_available_agents/memory_query_agent 默认策略 restricted (已接入
    # MeshActionBroker, 见 isac/agent/tools/base.py::DEFAULT_POLICY)。
    # CR2-Fix-19: restricted 不等于"LLM 不可见"——definitions() 只过滤 deny,
    # 这 4 个工具的定义仍会出现在 function-calling schema 里; 未注入
    # mesh_action_broker + mesh_link_policy 时调用在 execute() 阶段优雅失败
    # (拒绝, 不暴露 NotImplementedError)。以下 5 个是 Channel 交互工具
    # (send_emoji/send_image/fetch_history/switch_chat/view_forward_message),
    # 默认策略 allow, 与 Agent Mesh 无关。
    tools.register(NotifyAgentTool())
    tools.register(HandoffConversationTool())
    tools.register(ListAvailableAgentsTool())
    tools.register(MemoryQueryAgentTool())
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
    tools.register(DelegateTaskTool())
    tools.register(ListSubagentsTool())
    tools.register(SubagentStatusTool())
    tools.register(SubagentLogTool())
    tools.register(CancelSubagentTool())
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

    # D9 进度报告: 注入工厂 (默认无 sender → 惰性关闭, 主链路热路径零变化)。
    # 消息处理时用它构造 per-session Reporter 并绑定 Channel sender; persona_rendering
    # ="llm" 时复用本 Agent 已解析的 llm Provider 做受超时约束的文案改写。
    def _progress_reporter_factory(session_id, sender=None):  # noqa: ANN001, ANN202
        return build_progress_reporter(
            agent_id=config.agent_id,
            session_id=session_id,
            persona=config.persona,
            policy_config=config.persona.get("progress"),
            sender=sender,
            llm=llm,
        )

    agent_services["progress_reporter_factory"] = _progress_reporter_factory

    # CR2-Fix-1: 供 wait 工具等经 context.services 取用; 必须与 AgentInstance.agent_id
    # 一致 (manager._dispatch_message 用 instance.agent_id 写 ConversationRuntime,
    # 两处不一致会导致 wait 工具操作另一个 registry key, 永远等不到真实唤醒)。
    agent_services["agent_id"] = config.agent_id

    # P2: 注入 MeshActionBroker —— 4 个 A2A 工具 (notify/handoff/list/memory_query)
    # 的 restricted 门要求该服务存在, 此前生产零注入点使它们恒返回"未接入"。
    # 策略随 Link 配置 (broker.policy_for 按对端解析), 不再依赖单值 mesh_link_policy。
    bus = services.get("bus")
    if bus is not None:
        from isac.runtime.mesh.actions import MeshActionBroker

        agent_services["mesh_action_broker"] = MeshActionBroker(bus=bus)

    await _setup_conversation_runtime(config, global_config, agent_services, prompt_builder)

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
