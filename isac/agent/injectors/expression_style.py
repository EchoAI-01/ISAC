"""expression_style 注入器: 表达风格人格。"""

from __future__ import annotations

from isac.core.injector import PromptInjector
from isac.core.types import InjectionContext


class ExpressionStyleInjector(PromptInjector):
    """表达风格注入器 (正式度/详尽度/幽默/共情, SPECIFICATION.md 3.1 persona)。"""

    @property
    def key(self) -> str:
        return "expression_style"

    @property
    def priority(self) -> int:
        return 80

    async def build(self, context: InjectionContext) -> str:
        """读取 persona/style_profiles + UserProfile.expression_style 生成风格指令; 桩实现返回空。"""
        del context
        return ""
