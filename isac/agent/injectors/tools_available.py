"""tools_available 注入器: 可用工具说明。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.agent.injector import PromptInjector
from isac.core.types import InjectionContext

if TYPE_CHECKING:
    from isac.agent.tools.registry import ToolRegistry


class ToolsAvailableInjector(PromptInjector):
    """向 System Prompt 注入当前可用工具清单。"""

    def __init__(self, tools: ToolRegistry):
        self._tools = tools

    @property
    def key(self) -> str:
        return "tools_available"

    @property
    def priority(self) -> int:
        return 60

    async def build(self, context: InjectionContext) -> str:
        definitions = self._tools.definitions()
        if not definitions:
            return ""
        lines = ["你可以使用以下工具:"]
        for definition in definitions:
            lines.append(f"- {definition['name']}: {definition['description']}")
        return "\n".join(lines)
