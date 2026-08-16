"""Agent 组装器: 按 AgentConfig 组装独立子系统 (ARCHITECTURE.md 3.1)。

组装顺序遵循 DEVELOP.md 1.2 导入规则；共享服务 (ProviderManager 等) 注入。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from isac.agent.hooks import AgentHooks
from isac.agent.injectors.attention_drift import AttentionDriftInjector
from isac.agent.injectors.base_identity import BaseIdentityInjector
from isac.agent.injectors.expression_style import ExpressionStyleInjector
from isac.agent.injectors.interrupt import InterruptInjector
from isac.agent.injectors.model_capabilities import ModelCapabilitiesInjector
from isac.agent.injectors.mood import MoodInjector
from isac.agent.injectors.recovery import RecoveryInjector
from isac.agent.injectors.tools_available import ToolsAvailableInjector
from isac.agent.loop import ISACAgentLoop
from isac.agent.prompt_builder import SystemPromptBuilder
from isac.agent.tools.base import ToolPermission
from isac.agent.tools.media import (
    GenerateImageTool,
    GenerateVideoTool,
    SynthesizeSpeechTool,
    TranscribeAudioTool,
    UnderstandVideoTool,
    VisionUnderstandTool,
)
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
from isac.core.events import AgentHookPoint
from isac.core.policy import EnableMatrix
from isac.gating.system import GatingSystem
from isac.memory.consolidator import MemoryConsolidator
from isac.memory.injector.heuristic import HeuristicMemoryInjector
from isac.memory.injector.jargon import JargonInjector
from isac.memory.injector.mid_term import MidTermMemoryInjector
from isac.memory.injector.person_profile import PersonProfileInjector
from isac.persona.manager import PersonaManager
from isac.runtime.config import AgentConfig
from isac.runtime.conversation import (
    CompositeTaskProducer,
    ConversationRuntimeRegistry,
    ConversationStateStore,
    DateReminderProducer,
    IdleReengageProducer,
    MemoryAssociationProducer,
    ProactiveScheduler,
    ProactiveTask,
    TopicFollowupProducer,
)
from isac.runtime.instance import AgentInstance
from isac.runtime.progress import build_progress_reporter
from isac.utils.logger import get_logger

logger = get_logger(__name__)


def _build_task_producer(
    config: AgentConfig,
    proactive_cfg: dict,
    registry: ConversationRuntimeRegistry,
    memory: Any = None,
) -> Callable[[float], Awaitable[list[ProactiveTask]]] | None:
    """按配置收集启用的主动任务生产者, 组合成 ProactiveScheduler 期望的单个 callable。

    idle_reengage 默认关闭 (idle_reengage_seconds<=0 不接); 其余生产者默认关闭
    (*_enabled 默认 False)。S1 激活后, DateReminder/MemoryAssociation 需要 memory
    实例做检索 (memory=None 时恒返回 [], 零行为变化); TopicFollowup 只依赖
    message_cache, 不需要 memory 但接受参数以保持装配一致。未启用任何生产者
    时返回 None (调度器队列恒空, 与旧行为一致)。
    """
    idle_reengage_seconds = float(proactive_cfg.get("idle_reengage_seconds", 0) or 0)
    producers: list[Callable[[float], Awaitable[list[ProactiveTask]]]] = []
    if idle_reengage_seconds > 0:
        producers.append(
            IdleReengageProducer(
                agent_id=config.agent_id, registry=registry, idle_seconds=idle_reengage_seconds
            )
        )
    if bool(proactive_cfg.get("date_reminder_enabled", False)):
        producers.append(
            DateReminderProducer(agent_id=config.agent_id, registry=registry, memory=memory)
        )
    if bool(proactive_cfg.get("topic_followup_enabled", False)):
        followup_idle_seconds = float(proactive_cfg.get("followup_idle_seconds", 1800) or 1800)
        producers.append(
            TopicFollowupProducer(
                agent_id=config.agent_id, registry=registry,
                memory=memory, followup_idle_seconds=followup_idle_seconds,
            )
        )
    if bool(proactive_cfg.get("memory_association_enabled", False)):
        min_score = float(proactive_cfg.get("memory_association_min_score", 0.15) or 0.15)
        producers.append(
            MemoryAssociationProducer(
                agent_id=config.agent_id, registry=registry, memory=memory, min_score=min_score,
            )
        )
    if not producers:
        return None
    if len(producers) == 1:
        return producers[0]
    return CompositeTaskProducer(producers)


def _build_memory_consolidator(
    config: AgentConfig,
    global_config: dict,
    memory: Any,
    llm: Any = None,
) -> MemoryConsolidator | None:
    """按 memory.consolidation 配置构造后台整合器; 默认关闭 (enabled!=true → None)。

    S2 激活: run_once 真实三步 (去重/剪枝/画像归纳), 各步隔离异常; llm=None 时
    画像归纳步骤跳过 (返回 updated_profiles=0, 不报错)。NoOpMemoryPipeline (无
    metadata) 时不构造 (无可整合数据)。生命周期由 AgentManager 随 Agent start/stop 驱动。
    """
    consolidation_cfg = (global_config.get("memory", {}) or {}).get("consolidation", {}) or {}
    if not bool(consolidation_cfg.get("enabled", False)):
        return None
    metadata = getattr(memory, "metadata", None)
    if metadata is None:
        return None
    namespace = str(getattr(memory, "namespace", "") or config.effective_memory_namespace)
    # N5b 批次E 项2: 注入本 pipeline 的 sparse/vector resolver, 让 consolidator 去重/
    # 剪枝软删时同步 BM25/向量 (与控制面治理口径一致)。resolver 忽略传入 namespace
    # (consolidator 只处理自身 namespace, 取本 pipeline 的索引即可)。
    sparse_obj = getattr(memory, "sparse", None)
    vector_obj = getattr(memory, "vector", None)
    sparse_resolver = (lambda _ns: sparse_obj) if sparse_obj is not None else None
    vector_resolver = (lambda _ns: vector_obj) if vector_obj is not None else None
    return MemoryConsolidator(
        agent_id=config.agent_id,
        namespace=namespace,
        metadata=metadata,
        interval_seconds=float(consolidation_cfg.get("interval_seconds", 3600) or 3600),
        llm=llm,
        dedup_similarity=float(consolidation_cfg.get("dedup_similarity", 0.92) or 0.92),
        prune_after_days=int(consolidation_cfg.get("prune_after_days", 30) or 30),
        prune_importance_below=float(
            consolidation_cfg.get("prune_importance_below", 0.2) or 0.2
        ),
        sparse_resolver=sparse_resolver,
        vector_resolver=vector_resolver,
    )


def _register_compress_listener(hooks: AgentHooks, consolidator: MemoryConsolidator) -> None:
    """R4-②: 把 COMPRESS hook 回调注册进本 Agent 私有 hooks。

    回调仅做"入队" (session_id + messages 快照 → consolidator.enqueue_compression),
    不调 LLM (守护 hooks.py hook 内禁直接调 LLM 规范); 真实摘要在 consolidator
    后台 ``_compress_step`` 低频完成。失败由 AgentHooks.fire 的 try-except 兜底。
    """

    async def _on_compress(messages: Any, context: Any) -> None:
        session = getattr(context, "session", None)
        session_id = str(getattr(session, "session_id", "") or "") if session else ""
        if not session_id or not messages:
            return
        label = (
            f"agent={getattr(session, 'agent_id', '')};platform={getattr(session, 'platform', '')}"
            if session else ""
        )
        await consolidator.enqueue_compression(session_id, list(messages), context=label)

    hooks.register(AgentHookPoint.COMPRESS, _on_compress)


async def _setup_conversation_runtime(
    config: AgentConfig,
    global_config: dict,
    agent_services: dict[str, Any],
    prompt_builder: SystemPromptBuilder,
    memory: Any = None,
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
    # R2-2: 空闲重连生产者 —— 给主动任务队列一个真实的生产侧入口 (此前调度器只是
    # 消费者, 队列恒空, 主动任务功能不可达)。默认 idle_reengage_seconds=0 时不构造,
    # 主链路零行为变化; 配置 > 0 时会话静默超阈值即主动关心一次 (按新消息重新武装)。
    task_producer = _build_task_producer(
        config, proactive_cfg, agent_services["conversation_registry"], memory=memory
    )
    agent_services["proactive_scheduler"] = ProactiveScheduler(
        min_interval_seconds=float(proactive_cfg.get("min_interval_seconds", 600) or 0),
        poll_interval_seconds=float(proactive_cfg.get("poll_interval_seconds", 1.0) or 1.0),
        task_producer=task_producer,
    )
    # MVP-Fix: 快照目录跟随 control.agents_dir 配置 (此前硬编码默认 data/agents,
    # 测试与多实例部署都会写进同一处真实目录)。
    agents_dir = str((global_config.get("control", {}) or {}).get("agents_dir", "data/agents"))
    state_store = ConversationStateStore(base_dir=agents_dir)
    agent_services["conversation_state_store"] = state_store
    snapshots = await _asyncio.to_thread(state_store.load_all, config.agent_id)
    for stable_key, snapshot in snapshots.items():
        recovery_injector.add_snapshot(stable_key, snapshot)
    if snapshots:
        logger.info("会话拟人状态快照已恢复", agent_id=config.agent_id, count=len(snapshots))


def _register_media_tools(config: AgentConfig, tools: ToolRegistry) -> None:
    """R1-⑤: 按 AgentConfig.model_capabilities_allow 条件注册媒体工具。

    默认 ["*"] 全部允许 (向后兼容); 空 list 或指定子集只注册授权工具, 未授权的
    LLM schema 不可见。词汇用工具名 (与 ModelCapabilitiesInjector hints 一致)。
    """
    caps = list(getattr(config, "model_capabilities_allow", ["*"]) or ["*"])

    def _allowed(name: str) -> bool:
        return "*" in caps or name in caps

    if _allowed("generate_image"):
        tools.register(GenerateImageTool())
    if _allowed("generate_video"):
        tools.register(GenerateVideoTool())
    if _allowed("transcribe_audio"):
        tools.register(TranscribeAudioTool())
    if _allowed("synthesize_speech"):
        tools.register(SynthesizeSpeechTool())
    if _allowed("understand_image"):
        tools.register(VisionUnderstandTool())
    if _allowed("understand_video"):
        tools.register(UnderstandVideoTool())


def _merge_shared_plugin_tools(
    services: dict[str, Any], tools: ToolRegistry, prompt_builder: SystemPromptBuilder
) -> None:
    """R3: 合并进程级共享插件 tools/injectors 进 per-Agent registry。

    同 plugin_agent_hooks 合并模式 (assembly.py assemble_agent 内 269-273 行): 共享
    表是裸收集器, 合并进 per-Agent 后由 per-Agent 的 permission/enable_matrix 控可见性。
    native 插件经 on_load 主动 register, AstrBot/MaiBot 兼容层经 _adapt_compat_plugins
    调 adapter.adapt 注册到共享表 (_fire_plugin_on_load 收集)。默认无插件时空操作。
    shared_commands 合并由调用方在 commands 构造后单独处理 (commands 此处尚未构造)。
    """
    shared_tools = services.get("plugin_tools")
    if shared_tools is not None:
        for _name, _tool in shared_tools._tools.items():  # noqa: SLF001
            # T6: 透传共享表来源, 让 per-Agent registry 也带 source 追踪,
            # 否则热重载 deregister_by_source 在运行中 Agent 不生效。
            _src = shared_tools._source.get(_name, "builtin")  # noqa: SLF001
            tools.register(_tool, source=_src)
    shared_prompt = services.get("plugin_prompt_builder")
    if shared_prompt is not None:
        for _inj in shared_prompt._injectors:  # noqa: SLF001
            prompt_builder.register(_inj)


async def _wire_mcp_clients(
    config: AgentConfig, services: dict[str, Any], tools: ToolRegistry
) -> list[Any]:
    """R3: 按 AgentConfig.mcp_servers 构造并连接 MCPClient, MCP 工具注册进 tools。

    AgentConfig.mcp_servers (允许名列表) 查全局 services["mcp_servers"] (build_services
    注入, config.jsonc 顶层 mcp.servers 节)。逐 server 构造 MCPClient + connect +
    list_tools, MCPToolBridge (Tool 子类, client.py:268) 注册进 per-Agent tools。
    返回 MCPClient 实例列表 (供 agent_services["mcp_clients"] 存储, stop/destroy 时
    disconnect)。默认 mcp_servers=[] 或无全局定义时返回空列表, 零行为变化。
    逐 server 错误隔离, 失败不阻塞 Agent 启动。
    """
    mcp_clients: list[Any] = []
    mcp_servers_def = services.get("mcp_servers", {})
    if not config.mcp_servers or not mcp_servers_def:
        return mcp_clients
    from isac.agent.tools.mcp.client import MCPClient

    for _srv_name in config.mcp_servers:
        _srv_cfg = mcp_servers_def.get(_srv_name)
        if not _srv_cfg:
            logger.warning(
                "MCP server 配置缺失, 跳过",
                server=_srv_name, agent_id=config.agent_id,
            )
            continue
        try:
            _client = MCPClient(_srv_name, _srv_cfg)
            await _client.connect()
            _bridges = await _client.list_tools()
            for _bridge in _bridges:
                tools.register(_bridge)
            mcp_clients.append(_client)
            logger.info(
                "MCP server 已接入",
                server=_srv_name, agent_id=config.agent_id, tools=len(_bridges),
            )
        except Exception as exc:  # noqa: BLE001
            # N5b 批次D 项3: connect 成功但 list_tools 失败时, client 未进 mcp_clients
            # 列表 (append 在 list_tools 之后) → stop/destroy 的 disconnect 拿不到它
            # → 子进程/HTTP 连接泄漏。connect 成功必须配对 disconnect。
            try:
                await _client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            logger.warning(
                "MCP server 接入失败, 不阻塞 Agent",
                server=_srv_name, agent_id=config.agent_id,
                error=str(exc), exc_info=True,
            )
    return mcp_clients


def _merge_shared_plugin_commands(
    services: dict[str, Any], commands: CommandRegistry
) -> None:
    """R3: 合并进程级共享插件 commands 进 per-Agent CommandRegistry。

    同 plugin_agent_hooks 合并模式; 由 assemble_agent 在 commands 构造后调用
    (commands 在 tools 之后定义, 故不能并入 _merge_shared_plugin_tools)。
    默认无插件时空操作。
    """
    shared_commands = services.get("plugin_commands")
    if shared_commands is not None:
        for _cmd in shared_commands._commands.values():  # noqa: SLF001
            commands.register(_cmd)


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
    # Q2 激活: persona.description (Agent 级覆盖全局) 接入身份注入器, 使不同 Agent
    # 的人格文本在 System Prompt 中可辨; 未配置时两者皆空, 注入器自身回落默认文案
    # (零行为变化)。
    _identity_text = config.persona.get("description") or global_config.get("persona", {}).get("description")
    prompt_builder.register(BaseIdentityInjector(_identity_text))
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
    # Q3 激活: 6 个多模态语义工具接入生产 ToolRegistry。此前这些 Tool 类从未
    # 在 assembly 注册过, 即使配置了多模态 Provider 也调不到 (LLM schema 里
    # 根本看不到)。默认权限 deny (ToolPermission.DEFAULT_POLICY), 需 Agent 在
    # tools_policy 里显式开启对应能力 (如 {"generate_image": "allow"}) 才会
    # 出现在 LLM schema; model_router/artifact_store/media_normalizer 经 shared
    # services 自动流到 ToolContext.services (main.py 装配的键)。
    # R1-⑤: 媒体工具按 model_capabilities_allow 条件注册 (抽 helper 降 assemble_agent 复杂度)
    _register_media_tools(config, tools)

    # R3: 合并进程级共享插件 tools/injectors 进 per-Agent registry (同 plugin_agent_hooks
    # 合并模式; shared_commands 合并见下方 commands 定义后) + MCPClient 按
    # AgentConfig.mcp_servers 构造+connect+list_tools 注册 MCP 工具进 tools。client
    # 存 agent_services["mcp_clients"] 供 stop/destroy disconnect。默认空, 零行为变化。
    _merge_shared_plugin_tools(services, tools, prompt_builder)
    mcp_clients = await _wire_mcp_clients(config, services, tools)

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
    # R3: 合并进程级共享插件命令 (services["plugin_commands"]) 进 per-Agent
    # CommandRegistry, 同 plugin_agent_hooks 合并模式。默认空。
    _merge_shared_plugin_commands(services, commands)

    provider_manager = services["provider_manager"]
    llm = provider_manager.for_agent(config)
    memory = services["memory_factory"](config.effective_memory_namespace)
    prompt_builder.register(PersonProfileInjector(memory))
    prompt_builder.register(JargonInjector(memory))
    prompt_builder.register(HeuristicMemoryInjector(memory))
    prompt_builder.register(MidTermMemoryInjector(memory))
    agent_services = {**services, "memory": memory}
    # R3: MCPClient 引用 (上方构造) 存入 services, 供 AgentManager.stop/destroy
    # 与 _shutdown_message_pipeline 调 disconnect (避免子进程/HTTP 连接泄漏)。
    agent_services["mcp_clients"] = mcp_clients

    # 后台记忆整合器 (默认关闭: memory.consolidation.enabled!=true → None → 生命周期不启动)。
    # 骨架期 run_once 为 no-op, 由 AgentManager 随 Agent start/stop 驱动。
    consolidator = _build_memory_consolidator(config, global_config, memory, llm=llm)
    if consolidator is not None:
        agent_services["memory_consolidator"] = consolidator
        # R4-②: 注册 COMPRESS hook listener —— 仅入队待压缩会话快照到 consolidator
        # (不调 LLM, 守护 hooks.py "hook 内禁直接调 LLM" 规范); 真实摘要由 consolidator
        # 后台 _compress_step 低频完成。入队键为 session_id (回调拿不到 episode_id)。
        _register_compress_listener(hooks, consolidator)

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

    await _setup_conversation_runtime(config, global_config, agent_services, prompt_builder, memory=memory)

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
    # Q2 激活: 人格系统的三个注入器 (mood / expression_style / attention_drift)
    # 此前是空桩且未注册; 现在 PersonaManager 就绪后接入 prompt_builder, 让 LLM
    # 回复带出情绪色彩 + 表达风格 + 注意力漂移人格特征。无 mood_engine (如未
    # 启用 conversation) 时 MoodInjector 返回空串, 零行为变化。
    prompt_builder.register(MoodInjector(mood_engine=persona.mood_engine))
    prompt_builder.register(ExpressionStyleInjector(persona_manager=persona))
    prompt_builder.register(AttentionDriftInjector(level=persona.get_drift_level()))

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
