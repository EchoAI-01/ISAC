"""记忆检索注入器基类 (DEVELOP.md 4.3)。"""

from __future__ import annotations

from isac.core.injector import PromptInjector
from isac.core.types import MemoryHit
from isac.memory.pipeline import MemoryRetrievalPipeline


class MemoryInjector(PromptInjector):
    """记忆检索注入器基类。"""

    def __init__(self, pipeline: MemoryRetrievalPipeline):
        self.pipeline = pipeline

    async def search_and_format(self, query: str, top_k: int = 3, header: str = "【记忆-内部参考】") -> str:
        """通用检索 + 格式化流程。失败时返回空字符串。"""
        try:
            hits = await self.pipeline.search(query, top_k=top_k)
        except Exception:
            return ""
        if not hits:
            return ""
        return self._format_reference(hits, header=header)

    @staticmethod
    def _format_reference(hits: list[MemoryHit], header: str = "【记忆-内部参考】") -> str:
        """格式化为内部参考文本。"""
        lines = [header]
        for i, hit in enumerate(hits, 1):
            lines.append(f"{i}. {hit.content[:150]}")
        lines.append("(仅作为推理参考，不要向用户逐字复述)")
        return "\n".join(lines)
