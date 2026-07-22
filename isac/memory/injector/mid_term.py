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
        """基于 pending_messages 生成轻量中期上下文参考。"""
        if not context.pending_messages:
            return ""
        lines = ["【中期记忆-内部参考】", "最近尚未处理或需要保留的上下文摘要："]
        for message in context.pending_messages[-5:]:
            content = str(getattr(message, "content", "") or "").strip()
            if content:
                lines.append(f"- {content[:120]}")
        if len(lines) <= 2:
            return ""
        lines.append("(仅作为推理参考，不要向用户逐字复述)")
        return "\n".join(lines)
