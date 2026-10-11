"""插件激活与热重载同步辅助 (T6)。

从 ``main._fire_plugin_on_load`` / ``_adapt_compat_plugins`` 提取单插件可复用激活
逻辑, 供 reload/install 后激活使用。新增 ``sync_plugin_tools_to_agents`` 把共享
注册表的变更同步到运行中 Agent 的 per-Agent registry —— ISAC 是 per-Agent
ToolRegistry (非 AstrBot 全局表), reload 后新工具只进了进程级共享表
(`plugin_tools` 服务键), 运行中 Agent 的 ``instance.tools`` 仍是旧的, 必须
遍历 ``agent_manager.list()`` 把旧工具 deregister + 新工具 register 同步到每个
运行中 Agent, 热重载才对运行中会话真正生效。

导入顺序: 本模块在 plugin.runtime 层, 不 module-level import ``runtime.*`` (单向
无环 plugin < runtime); AgentManager 用 TYPE_CHECKING 注解, 运行时鸭子类型调
``agent_manager.list()``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.runtime.manager import AgentManager

logger = get_logger(__name__)


async def ensure_shared_registries(services: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    """惰性创建进程级共享注册表 (复用 _fire_plugin_on_load 的 setdefault 模式)。

    返回 (shared_tools, shared_commands, shared_prompt, plugin_agent_hooks)。
    setdefault 幂等, 多次调用 (首次批量激活 + reload 单插件激活) 安全。
    """
    from isac.agent.hooks import AgentHooks
    from isac.agent.prompt_builder import SystemPromptBuilder
    from isac.agent.tools.registry import ToolRegistry
    from isac.commands.registry import CommandRegistry

    shared_tools = services.setdefault("plugin_tools", ToolRegistry())
    shared_commands = services.setdefault("plugin_commands", CommandRegistry())
    shared_prompt = services.setdefault("plugin_prompt_builder", SystemPromptBuilder())
    plugin_agent_hooks = services.setdefault("plugin_agent_hooks", AgentHooks())
    return shared_tools, shared_commands, shared_prompt, plugin_agent_hooks


async def activate_plugin(
    plugin_manager: Any,
    name: str,
    services: dict[str, Any],
    *,
    event_bus: Any = None,
    bus: Any = None,
    router: Any = None,
) -> str:
    """激活单个插件: set_current_source → on_load (native) 或 adapt (compat)。

    供 reload/install 后激活。event_bus=None 时返回 "skipped" (与 _fire_plugin_on_load
    一致 —— 极少数测试路径无 event_bus, 不构造无效 context)。失败记日志返回
    "failed: <error>", 不 raise (调用方按状态码处理)。

    关键: set_current_source(name) 让插件 on_load / adapter.adapt 注册的工具标记
    source=name, 供热重载 deregister_by_source(name) 精确移除。
    """
    if event_bus is None:
        logger.debug("event_bus 未注入, 跳过插件激活", plugin=name)
        return "skipped"
    try:
        from isac.plugin.native.plugin import make_plugin_context

        shared_tools, shared_commands, shared_prompt, plugin_agent_hooks = (
            await ensure_shared_registries(services)
        )
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
        # C2: 对全部 source-aware registry 统一设 source=name (非仅 tools), 让插件注册的
        # 命令/注入器/钩子/事件订阅也标来源, 卸载时精确 deregister。直接用 ensure_shared_registries
        # 返回的变量 + event_bus (不依赖 PluginContext 属性名, 与 call_on_load 批量路径同效)。
        registries = [
            r for r in (shared_tools, shared_commands, shared_prompt, plugin_agent_hooks, event_bus)
            if r is not None and hasattr(r, "set_current_source")
        ]
        for r in registries:
            r.set_current_source(name)
        try:
            loaded = plugin_manager.get(name) if hasattr(plugin_manager, "get") else None
            is_compat = loaded is not None and (
                getattr(loaded, "is_astrbot", lambda: False)()
                or getattr(loaded, "is_maibot", lambda: False)()
            )
            if is_compat:
                status = await plugin_manager.adapt_one(name, shared_tools, shared_commands)
            else:
                status = await plugin_manager.call_on_load_one(name, context)
        finally:
            for r in registries:
                r.set_current_source(None)
        return status
    except Exception as exc:  # noqa: BLE001
        logger.warning("插件激活失败", plugin=name, error=str(exc), exc_info=True)
        return f"failed: {exc}"


def _sync_sourced(target: Any, shared: Any, plugin_name: str | None, config: Any = None) -> None:
    """C2 通用按来源同步: 精确模式 deregister_by_source + get_by_source re-register;
    全量模式 deregister_plugin_sourced + 全量 re-register (带 source)。

    target/shared 需实现 deregister_by_source / get_by_source / deregister_plugin_sourced /
    register(item, source=) + (全量模式) 迭代 items + _source 映射。commands/injectors 共用。
    D5: 两模式均按该 Agent 的 plugins_allow/deny 过滤 (与 tools 同口径)。
    """
    if target is None or shared is None:
        return
    if plugin_name is not None:
        target.deregister_by_source(plugin_name)
        if _plugin_enabled_for_instance(config, plugin_name):
            for item in shared.get_by_source(plugin_name):
                target.register(item, source=plugin_name)
        return
    target.deregister_plugin_sourced()
    for item, src in shared.items_with_source():  # type: ignore[attr-defined]
        if src != "builtin" and not _plugin_enabled_for_instance(config, src):
            continue
        target.register(item, source=src)


def _plugin_enabled_for_instance(config: Any, plugin_name: str) -> bool:
    """运行中 Agent 的插件启用判定 (鸭子类型, 与初始装配 assembly 同语义)。

    D5 (2026-10-11 审计修复): reload/install 后的同步此前**不查启用矩阵**, 把共享
    表中该插件来源的工具/命令/注入器直接灌回每个 running Agent —— 配置
    plugins_deny 或受限默认 plugins_allow=[] 的 Agent 被绕过 (权限提升)。
    语义收口 core.policy.plugin_allowed_by_agent_lists (plugin 层不 import runtime,
    AgentConfig 用鸭子类型取 plugins_allow/plugins_deny 两字段)。

    config 缺失时放行并记告警: 生产 AgentInstance.config 必填 (assemble_agent
    构造必传), 缺失仅见于测试替身 —— 放行保持既有行为兼容, 告警保证可观测。
    """
    from isac.core.policy import plugin_allowed_by_agent_lists

    if config is None:
        logger.warning("实例缺少 config, 插件启用矩阵无法判定, 按放行处理", plugin=plugin_name)
        return True
    allow = list(getattr(config, "plugins_allow", []) or [])
    deny = list(getattr(config, "plugins_deny", []) or [])
    return plugin_allowed_by_agent_lists(allow, deny, plugin_name)


def _sync_one_instance(
    instance: Any,
    shared_tools: Any,
    shared_commands: Any,
    shared_prompt: Any,
    plugin_name: str | None,
) -> list[str]:
    """同步单个运行中 Agent 的 registry, 返回被移除的工具名列表。

    D5: 同步前按该 Agent 的 plugins_allow/deny 过滤 (与初始装配同口径) ——
    未启用的插件只移除旧条目、不灌入新条目; 全量模式同理按来源逐插件判定。
    """
    config = getattr(instance, "config", None)
    tools = getattr(instance, "tools", None)
    removed: list[str] = []
    if tools is not None:
        if plugin_name is not None:
            removed = tools.deregister_by_source(plugin_name)
            if _plugin_enabled_for_instance(config, plugin_name):
                for tool in shared_tools.get_by_source(plugin_name):
                    tools.register(tool, source=plugin_name)
        else:
            removed = tools.deregister_plugin_sourced()
            for tool_name, tool in shared_tools._tools.items():  # noqa: SLF001
                source = shared_tools._source.get(tool_name, "builtin")  # noqa: SLF001
                if source != "builtin" and not _plugin_enabled_for_instance(config, source):
                    continue
                tools.register(tool, source=source)
    # C2: commands/injectors 精确同步 (此前全量 re-register 加法语义, 旧的不同名残留;
    # 改为按来源 deregister + re-register, 与 tools 同款)。D5: 同样过启用矩阵。
    _sync_sourced(getattr(instance, "commands", None), shared_commands, plugin_name, config)
    _sync_sourced(getattr(instance, "prompt_builder", None), shared_prompt, plugin_name, config)
    return removed


async def sync_plugin_tools_to_agents(
    agent_manager: AgentManager,
    services: dict[str, Any],
    plugin_name: str | None = None,
) -> dict[str, list[str]]:
    """把共享注册表的变更同步到运行中 Agent 的 per-Agent registry。

    精确模式 (plugin_name 非 None): 对每个 running Agent, ``deregister_by_source(name)``
    + 重新 ``register`` 共享表中 source=name 的工具。
    全量模式 (plugin_name=None): ``deregister_plugin_sourced()`` + 重新合并共享表全部
    工具 (带 source 追踪)。

    commands/injectors 同样按来源精确 deregister + re-register (C2: 此前是加法语义
    re-register, 旧的不同名残留; 现 CommandRegistry/SystemPromptBuilder 已加来源追踪,
    sync 对 commands/injectors 与 tools 同款按 source 精确同步)。hooks/event_bus 共享
    表的卸载清理在 routes_plugins._deregister_shared_by_source 处理。

    返回 ``{agent_id: [被移除的工具名]}`` 供审计/日志。
    """
    from isac.runtime.services import ServiceContainer

    container = services if isinstance(services, ServiceContainer) else ServiceContainer(services)
    shared_tools = container.plugin_tools
    shared_commands = container.plugin_commands
    shared_prompt = container.plugin_prompt_builder
    result: dict[str, list[str]] = {}
    if shared_tools is None:
        return result

    for instance in await agent_manager.list():
        if getattr(instance, "status", "stopped") != "running":
            continue
        aid = getattr(instance, "agent_id", "?")
        result[aid] = _sync_one_instance(instance, shared_tools, shared_commands, shared_prompt, plugin_name)

    return result
