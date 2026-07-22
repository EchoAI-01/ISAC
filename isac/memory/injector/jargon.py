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
        """匹配当前消息中的行话并注入解释。"""
        metadata = getattr(self.pipeline, "metadata", None)
        if metadata is None or not hasattr(metadata, "list_jargon"):
            return ""
        content = str(getattr(context.current_message, "content", "") or "")
        if not content:
            return ""
        try:
            entries = await metadata.list_jargon(getattr(context.session, "agent_id", ""))
        except Exception:
            return ""
        matched = [entry for entry in entries if str(entry.get("word", "")) and str(entry.get("word", "")) in content]
        if not matched:
            return ""
        lines = ["【行话-内部参考】"]
        for entry in matched[:5]:
            context_text = f"；语境：{entry.get('context')}" if entry.get("context") else ""
            lines.append(f"- {entry.get('word')}：{entry.get('meaning')}{context_text}")
        lines.append("(仅作为推理参考，不要向用户逐字复述)")
        return "\n".join(lines)
