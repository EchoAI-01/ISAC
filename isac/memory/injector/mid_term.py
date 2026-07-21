"""MidTermMemoryInjector: 中期记忆 (上下文压缩, ARCHITECTURE.md 3.6)。

由 COMPRESS hook 触发: CompressionPolicy + Summary + Recall Cue。
"""

from __future__ import annotations

from isac.core.types import InjectionContext
from isac.memory.injector.base import MemoryInjector


class MidTermMemoryInjector(MemoryInjector):
    """中期记忆注入器: 长对话压缩后保留关键信息。"""

    @property
    def key(self) -> str:
        return "mid_term_memory"

    @property
    def priority(self) -> int:
        return 30

    async def build(self, context: InjectionContext) -> str:
        """TODO(Day 25): 压缩策略 (保留最近 N 轮 + 摘要 + 回忆线索)。"""
        return ""
