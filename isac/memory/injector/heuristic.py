"""HeuristicMemoryInjector: 启发式长期记忆自然拉起 (ARCHITECTURE.md 3.6)。

每 3 分钟最多触发一次，且需要至少 60 条新消息 (core/constants.py)。
使用 LLM 生成当前聊天印象，再搜索相关记忆。
"""

from __future__ import annotations

from isac.core.constants import HEURISTIC_MEMORY_COOLDOWN_SECONDS, HEURISTIC_MEMORY_MIN_NEW_MESSAGES
from isac.core.types import InjectionContext
from isac.memory.injector.base import MemoryInjector
from isac.memory.pipeline import MemoryRetrievalPipeline


class HeuristicMemoryInjector(MemoryInjector):
    """启发式记忆注入器 (注册为 PRE_LLM hook 之外的低频注入器)。"""

    def __init__(self, pipeline: MemoryRetrievalPipeline):
        super().__init__(pipeline)

    @property
    def key(self) -> str:
        return "heuristic_memory"

    @property
    def priority(self) -> int:
        return 40

    @property
    def max_frequency_seconds(self) -> float:
        return float(HEURISTIC_MEMORY_COOLDOWN_SECONDS)

    @property
    def max_new_messages(self) -> int:
        return HEURISTIC_MEMORY_MIN_NEW_MESSAGES

    @property
    def tokens_estimate(self) -> int:
        return 500

    async def build(self, context: InjectionContext) -> str:
        """使用当前消息文本搜索相关长期记忆。"""
        query = str(getattr(context.current_message, "content", "") or "").strip()
        if not query:
            return ""
        return await self.search_and_format(query, top_k=3, header="【启发式记忆-内部参考】")
