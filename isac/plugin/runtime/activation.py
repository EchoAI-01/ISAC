"""插件激活与热重载同步辅助 (T6)。

从 ``main._fire_plugin_on_load`` / ``_adapt_compat_plugins`` 提取单插件可复用激活
逻辑, 供 reload/install 后激活使用。新增 ``sync_plugin_tools_to_agents`` 把共享
注册表的变更同步到运行中 Agent 的 per-Agent registry —— ISAC 是 per-Agent
ToolRegistry (非 AstrBot 全局表), reload 后新工具只进了进程级共享表
(``services["plugin_tools"]``), 运行中 Agent 的 ``instance.tools`` 仍是旧的, 必须
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
        shared_tools.set_current_source(name)
        loaded = plugin_manager.get(name) if hasattr(plugin_manager, "get") else None
        is_compat = loaded is not None and (
            getattr(loaded, "is_astrbot", lambda: False)()
            or getattr(loaded, "is_maibot", lambda: False)()
        )
        if is_compat:
            status = await plugin_manager.adapt_one(name, shared_tools, shared_commands)
        else:
            status = await plugin_manager.call_on_load_one(name, context)
        shared_tools.set_current_source(None)
        return status
    except Exception as exc:  # noqa: BLE001
        logger.warning("插件激活失败", plugin=name, error=str(exc), exc_info=True)
        return f"failed: {exc}"


def _sync_one_instance(
    instance: Any,
    shared_tools: Any,
    shared_commands: Any,
    shared_prompt: Any,
    plugin_name: str | None,
) -> list[str]:
    """同步单个运行中 Agent 的 registry, 返回被移除的工具名列表。"""
    tools = getattr(instance, "tools", None)
    if tools is None:
        return []
    if plugin_name is not None:
        removed = tools.deregister_by_source(plugin_name)
        for tool in shared_tools.get_by_source(plugin_name):
            tools.register(tool, source=plugin_name)
    else:
        removed = tools.deregister_plugin_sourced()
        for tool_name, tool in shared_tools._tools.items():  # noqa: SLF001
            source = shared_tools._source.get(tool_name, "builtin")  # noqa: SLF001
            tools.register(tool, source=source)
    # commands: 幂等 re-register (加法语义)
    cmds = getattr(instance, "commands", None)
    if shared_commands is not None and cmds is not None:
        for cmd in shared_commands._commands.values():  # noqa: SLF001
            cmds.register(cmd)
    # injectors: 幂等 re-register (加法语义)
    prompt_builder = getattr(instance, "prompt_builder", None)
    if shared_prompt is not None and prompt_builder is not None:
        for inj in shared_prompt._injectors:  # noqa: SLF001
            prompt_builder.register(inj)
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

    commands/injectors 幂等 re-register (加法语义: 同名覆盖, 旧的不同名残留 —— 已知
    限制, 仅 tools 做了精确 deregister; 后续可给 SystemPromptBuilder/CommandRegistry
    加来源追踪)。

    返回 ``{agent_id: [被移除的工具名]}`` 供审计/日志。
    """
    shared_tools = services.get("plugin_tools")
    shared_commands = services.get("plugin_commands")
    shared_prompt = services.get("plugin_prompt_builder")
    result: dict[str, list[str]] = {}
    if shared_tools is None:
        return result

    for instance in await agent_manager.list():
        if getattr(instance, "status", "stopped") != "running":
            continue
        aid = getattr(instance, "agent_id", "?")
        result[aid] = _sync_one_instance(instance, shared_tools, shared_commands, shared_prompt, plugin_name)

    return result
