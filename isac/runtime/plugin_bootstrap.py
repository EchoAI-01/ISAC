"""U2 插件与集成装配: MCP server / workflow 引擎 / 插件 on_load / compat 桥接。

原 isac/main.py 插件集成段拆出 (U2 装配层重构)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from isac.core.policy import EnableMatrix
from isac.router.router import MessageRouter
from isac.runtime.application import ApplicationRuntime
from isac.runtime.bus import InterAgentBus
from isac.runtime.manager import AgentManager
from isac.utils.logger import get_logger

logger = get_logger(__name__)

DATA_DIR = Path("data")

def _register_mcp_server(
    runtime: ApplicationRuntime,
    control_config: dict[str, Any],
    services: dict[str, Any] | None,
    agent_manager: AgentManager,
    router: MessageRouter,
    bus: InterAgentBus,
    plugin_manager: Any,
    audit_log: Any = None,
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
        agents_dir=str(control_config.get("agents_dir", "data/agents")),
        # Fix-93: 注入共享 AuditLog, 11 个写工具成功后统一留痕 (此前绕过审计)。
        audit_log=audit_log,
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

    agent_hooks 是进程级共享注册表 (`plugin_agent_hooks` 服务键), 组装每个
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
    loaded: dict[str, Any] = getattr(plugin_manager, "_loaded", {})
    for name, plugin in loaded.items():
        await _adapt_one_compat_plugin(name, plugin, shared_tools, shared_commands)


async def _adapt_one_compat_plugin(
    name: str, plugin: Any, shared_tools: Any, shared_commands: Any
) -> None:
    """U0 Fix-88: 桥接单个兼容层插件 (从 _adapt_compat_plugins 抽出降 C901)。

    按插件名设 current_source, 让桥接的工具/命令标 source=name 并加 <plugin>: 前缀
    (确定性命名空间隔离); 与 activate_plugin 单插件路径同构。失败只记日志不 raise。
    """
    instance = getattr(plugin, "instance", None)
    if instance is None:
        return
    registries = [
        r for r in (shared_tools, shared_commands)
        if r is not None and hasattr(r, "set_current_source")
    ]
    for r in registries:
        r.set_current_source(name)
    try:
        await _run_compat_adapt(name, plugin, instance, shared_tools, shared_commands)
    except ImportError as exc:
        logger.debug("兼容层适配器不可用, 跳过桥接", plugin=name, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("兼容层插件桥接失败, 跳过该插件", plugin=name, error=str(exc), exc_info=True)
    finally:
        for r in registries:
            r.set_current_source(None)


async def _run_compat_adapt(
    name: str, plugin: Any, instance: Any, shared_tools: Any, shared_commands: Any
) -> None:
    """U0 Fix-88: 按插件类型调对应 adapter.adapt 并记录桥接结果 (拆出降 C901)。"""
    if getattr(plugin, "is_astrbot", lambda: False)():
        from isac.plugin.compatibility.astrbot.adapter import AstrBotStarAdapter

        result = await AstrBotStarAdapter(instance).adapt(shared_tools)
        if result.get("tools") or result.get("hooks"):
            logger.info(
                "AstrBot 插件已桥接", plugin=name,
                tools=result.get("tools"), pending_hooks=result.get("hooks"),
            )
    elif getattr(plugin, "is_maibot", lambda: False)():
        from isac.plugin.compatibility.maibot.plugin import MaiBotPluginAdapter

        result = await MaiBotPluginAdapter(instance).adapt(shared_tools, shared_commands)
        if result.get("tools") or result.get("commands"):
            logger.info(
                "MaiBot 插件已桥接", plugin=name,
                tools=result.get("tools"), commands=result.get("commands"),
            )


def _build_plugin_enable_matrix(services: dict[str, Any] | None) -> EnableMatrix:
    """Q3: 从 global_config 构造 PluginManager 的 EnableMatrix (Agent ∩ Channel ∩ 全局)。

    从 shared services 的 global_config 读取 policy 与 channels.matrix, 构造全局
    EnableMatrix。未注入 global_config 时返回空矩阵 (默认放行, 向后兼容)。
    """
    from isac.runtime.services import ServiceContainer

    global_cfg = ServiceContainer(services).global_config if isinstance(services, dict) else None
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
