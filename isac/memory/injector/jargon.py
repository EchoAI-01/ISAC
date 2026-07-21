"""JargonInjector: 行话检测 + 解释注入 (每轮, ARCHITECTURE.md 3.6)。"""

from __future__ import annotations

from isac.core.types import InjectionContext
from isac.memory.injector.base import MemoryInjector


class JargonInjector(MemoryInjector):
    """行话注入器: 检测消息中的行话并注入解释。"""

    @property
    def key(self) -> str:
        return "jargon"

    @property
    def priority(self) -> int:
        return 50

    @property
    def tokens_estimate(self) -> int:
        return 200

    async def build(self, context: InjectionContext) -> str:
        """TODO(Day 25): 匹配 jargon_entries (按 agent_id) → 解释注入。"""
        return ""
