"""AstrBot Star 批量适配器 (R3, 对标 MaiBotPluginAdapter)。

扫描 Star 实例上 @filter.llm_tool / @filter.on_* 装饰器标记的方法, 批量桥接为
ISAC Tool / Hook。此前只有单函数桥接原语 (bridge_function_tool), 全仓无"扫描
Star 实例收集标记"的入口 —— loader 加载 AstrBot 插件后 @filter.llm_tool 标记的
handler 在生产是死代码。本适配器补齐该缺口。

本轮聚焦 tools 桥接 (@filter.llm_tool → FunctionToolAdapter → ToolRegistry),
对齐 MaiBotPluginAdapter 的范围 (MaiBot 亦只桥接 action/command, 不含 hook)。
@filter.on_message / @filter.on_llm_request 标记的 hook 在扫描阶段收集并记录,
其 EventBus/AgentHooks 签名适配 (AstrBot handler 期望 (ctx, event) 两参, 与 ISAC
EventBus/AgentHooks.fire 调用约定不同) 作为已知限制留后续。
"""

from __future__ import annotations

from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)


class AstrBotStarAdapter:
    """AstrBot Star 插件 → ISAC 适配器。

    扫描插件实例方法上的装饰器标记:
    - _isac_llm_tool: (name, description) → bridge_function_tool 注册为 ISAC Tool
    - _isac_event: str (on_message / on_llm_request) → 收集, 待后续 hook 签名适配

    加载时把适配结果注册到 ISAC ToolRegistry。
    """

    def __init__(self, star_instance: Any):
        self._plugin = star_instance
        self._tools: list[tuple[str, str, Any]] = []  # (name, description, method)
        self._hooks: list[tuple[str, Any]] = []  # (event_name, method)
        self._scan_decorators()

    def _scan_decorators(self) -> None:
        """扫描插件实例上的方法, 收集装饰器标记。

        bound method 取 getattr(instance, name) 后仍可读到函数属性 (method 对象
        代理函数属性), 故 _isac_llm_tool / _isac_event 可被 getattr 取到。
        """
        for attr_name in dir(self._plugin):
            if attr_name.startswith("_"):
                continue
            try:
                method = getattr(self._plugin, attr_name)
            except Exception:  # noqa: BLE001 防御: 某些属性访问可能抛异常
                continue
            if not callable(method):
                continue
            llm_tool = getattr(method, "_isac_llm_tool", None)
            if llm_tool:
                # _isac_llm_tool 是 (name, description) 2-tuple (star.py:62)
                self._tools.append((llm_tool[0], llm_tool[1], method))
            event = getattr(method, "_isac_event", None)
            if event:
                self._hooks.append((event, method))

    @property
    def tools(self) -> list[tuple[str, str, Any]]:
        return list(self._tools)

    @property
    def hooks(self) -> list[tuple[str, Any]]:
        return list(self._hooks)

    async def adapt(self, tools_registry: Any | None = None) -> dict[str, Any]:
        """把 @filter.llm_tool 标记的方法桥接为 ISAC Tool 注册, 返回注册清单。

        Args:
            tools_registry: 进程级共享 ToolRegistry (services["plugin_tools"])。
                None 时只扫描不注册 (向后兼容单测路径)。

        Returns:
            {"tools": [注册的 tool name 清单], "hooks": [未桥接的 event name 清单]}
        """
        from isac.plugin.compatibility.astrbot.tools import bridge_function_tool

        registered_tools: list[str] = []

        for name, description, func in self._tools:
            if tools_registry is None:
                continue
            tool = bridge_function_tool(name, description, func)
            tools_registry.register(tool)
            registered_tools.append(name)

        # hook 桥接: AstrBot handler (ctx, event) 签名与 ISAC EventBus/AgentHooks
        # 调用约定不同, 本轮只收集并记录, 签名适配留后续 (见模块 docstring)。
        pending_hooks = [event for event, _ in self._hooks]

        logger.info(
            "AstrBot 插件适配完成",
            plugin=type(self._plugin).__name__,
            tools=registered_tools,
            pending_hooks=pending_hooks,
        )
        return {"tools": registered_tools, "hooks": pending_hooks}
