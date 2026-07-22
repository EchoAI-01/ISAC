"""AstrBot Context API 模拟 (P1 兼容策略, ARCHITECTURE.md 3.8)。

把 AstrBot 的 Context 对象映射到 ISAC 的 ChannelRegistry / ProviderManager / Memory 等服务。
插件通过 Context 调用平台/LLM/记忆时, 实际委托到 ISAC 注入的服务。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.agent.tools.registry import ToolRegistry
    from isac.channel.registry import ChannelRegistry
    from isac.gateway.event_bus import EventBus
    from isac.provider.manager import ProviderManager


class ContextAdapter:
    """AstrBot Context → ISAC 适配器。

    持有 ISAC 注入的 services (channel_registry/provider_manager/event_bus/...),
    把 AstrBot 插件对 context.get_platform / context.get_provider 等调用
    转换为对 ISAC 服务的查询。
    """

    def __init__(self, services: dict[str, Any]):
        self.services = services
        # 缓存常用引用
        self._channel_registry: ChannelRegistry | None = services.get("channel_registry")
        self._provider_manager: ProviderManager | None = services.get("provider_manager")
        self._event_bus: EventBus | None = services.get("event_bus")
        self._tools: ToolRegistry | None = services.get("tools")

    async def send_message(self, message: str, platform: str | None = None) -> None:
        """AstrBot Context.send_message → 经 ChannelRegistry 发送文本。"""
        from isac.channel.model import ISACMessage

        if self._channel_registry is None or not platform:
            raise RuntimeError("未注入 channel_registry 或 platform, 无法发送消息")
        adapter = self._channel_registry.get(platform)
        if adapter is None:
            raise RuntimeError(f"平台 {platform} 未注册")
        msg = ISACMessage(
            msg_id="",
            platform=platform,
            timestamp=0,
            user_id="",
            user_name="",
            content=message,
        )
        await adapter.send(msg)

    def get_platform(self, platform_name: str) -> Any | None:
        """AstrBot Context.get_platform → ChannelRegistry.get。"""
        if self._channel_registry is None:
            return None
        return self._channel_registry.get(platform_name)

    def get_provider(self, provider_name: str | None = None) -> Any | None:
        """AstrBot Context.get_provider → ProviderManager (全局 Provider)。"""
        if self._provider_manager is None:
            return None
        return self._provider_manager

    def register_tool(self, name: str, description: str, func: Any) -> None:
        """AstrBot @filter.llm_tool 装饰器 → 注册到 ISAC ToolRegistry。"""
        from isac.plugin.compatibility.astrbot.tools import bridge_function_tool

        if self._tools is None:
            raise RuntimeError("未注入 tools, 无法注册工具")
        wrapped = bridge_function_tool(name, description, func)
        self._tools.register(wrapped)


def make_context(services: dict[str, Any]) -> ContextAdapter:
    """工厂: 用 services 创建 ContextAdapter (供插件 __init__ 调用)。"""
    return ContextAdapter(services)
