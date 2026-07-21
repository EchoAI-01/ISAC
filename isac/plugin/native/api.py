"""ISAC Native SDK 公开 API 面 (插件开发者的统一入口)。

用法: from isac.plugin.native.api import ISACPlugin, PluginContext, Tool, Command
"""

from isac.agent.injector import PromptInjector
from isac.agent.tools.base import Tool, ToolContext
from isac.commands.base import Command
from isac.core.events import AgentHookPoint, EventType
from isac.core.types import ToolResult
from isac.plugin.native.hooks import InterAgentHookPoint
from isac.plugin.native.plugin import ISACPlugin, PluginContext

__all__ = [
    "AgentHookPoint",
    "Command",
    "EventType",
    "ISACPlugin",
    "InterAgentHookPoint",
    "PluginContext",
    "PromptInjector",
    "Tool",
    "ToolContext",
    "ToolResult",
]
