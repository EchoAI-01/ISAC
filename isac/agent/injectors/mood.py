"""mood 注入器: 情绪状态注入。

职责区分 (DEVELOPMENT_PLAN.md Day 29): persona/mood.py 负责情绪状态计算，
本注入器负责将其注入 Prompt，职责不重叠。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.agent.injector import PromptInjector
from isac.core.types import InjectionContext

if TYPE_CHECKING:
    from isac.persona.mood import MoodEngine


class MoodInjector(PromptInjector):
    """情绪状态注入器。"""

    def __init__(self, mood_engine: MoodEngine | None = None):
        self._mood_engine = mood_engine

    @property
    def key(self) -> str:
        return "mood_system"

    @property
    def priority(self) -> int:
        return 70

    async def build(self, context: InjectionContext) -> str:
        """TODO(Day 29): 读取 MoodEngine 当前情绪 → 生成情绪提示文案。"""
        return ""
