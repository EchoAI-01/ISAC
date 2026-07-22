"""skill_selector 注入器: 技能选择提示。"""

from __future__ import annotations

from isac.core.injector import PromptInjector
from isac.core.types import InjectionContext


class SkillSelectorInjector(PromptInjector):
    """技能选择注入器: 根据上下文提示 Agent 可用技能/策略。"""

    @property
    def key(self) -> str:
        return "skill_selector"

    @property
    def priority(self) -> int:
        return 60

    async def build(self, context: InjectionContext) -> str:
        """基于会话上下文选择相关技能说明注入; 桩实现返回空。"""
        del context
        return ""
