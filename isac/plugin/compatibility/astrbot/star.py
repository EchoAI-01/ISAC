"""AstrBot Star 基类兼容 (SPECIFICATION.md 2.7)。

插件作者继承 Star, 在类内用 @filter.llm_tool / @filter.on_* 装饰方法,
ISAC 兼容层保留 Star 基类与注册流程, 装饰器桥接到 ISAC ToolRegistry / EventBus。
"""

from __future__ import annotations

from typing import Any


class Star:
    """兼容 astrbot.api.star.Star。

    子类用 @filter.llm_tool 装饰方法注册工具; @filter.on_message 注册事件回调。
    兼容层在加载子类时扫描这些装饰器, 转换为 ISAC Tool / Hook。
    """

    # 装饰器扫描结果: [(method, decorator_name, args)]
    _registered_tools: list[tuple[str, Any]] = []
    _registered_hooks: list[tuple[str, str, Any]] = []

    def __init__(self, context: Any):
        self.context = context

    async def terminate(self) -> None:
        """插件卸载时调用 (清理资源)。"""


class StarContext:
    """兼容 AstrBot Context 对象 (alias of ContextAdapter)。"""

    def __init__(self, services: dict[str, Any]):
        from isac.plugin.compatibility.astrbot.context import ContextAdapter

        self._adapter = ContextAdapter(services)

    async def send_message(self, message: str, platform: str | None = None) -> None:
        await self._adapter.send_message(message, platform)

    def get_platform(self, platform_name: str) -> Any | None:
        return self._adapter.get_platform(platform_name)

    def get_provider(self, provider_name: str | None = None) -> Any | None:
        return self._adapter.get_provider(provider_name)


# AstrBot @filter 装饰器实现的等价物 (供插件代码使用)
class _FilterRegistry:
    """AstrBot `from astrbot.api import filter` 的兼容实现。

    用法:
        @filter.llm_tool(name="my_tool", description="...")
        def my_tool(self, ctx, args): ...
    """

    def llm_tool(self, name: str | None = None, description: str = "") -> Any:
        """注册 llm_tool: 把方法包装为 ISAC Tool。"""

        def decorator(func: Any) -> Any:
            tool_name = name or func.__name__
            func._isac_llm_tool = (tool_name, description or func.__doc__ or "")  # type: ignore[attr-defined]
            return func

        return decorator

    def on_message(self) -> Any:
        """注册 on_message 钩子。"""

        def decorator(func: Any) -> Any:
            func._isac_event = "on_message"  # type: ignore[attr-defined]
            return func

        return decorator

    def on_llm_request(self) -> Any:
        """注册 PRE_LLM 钩子。"""

        def decorator(func: Any) -> Any:
            func._isac_event = "on_llm_request"  # type: ignore[attr-defined]
            return func

        return decorator


filter = _FilterRegistry()
