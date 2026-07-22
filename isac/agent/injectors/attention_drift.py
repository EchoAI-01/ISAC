"""attention_drift 注入器: 注意力漂移人格 (ARCHITECTURE.md 3.4)。

读取 persona/drift_profiles 配置，通过 locales 获取本地化漂移文案 (ADR-006)。
"""

from __future__ import annotations

from isac.core.injector import PromptInjector
from isac.core.types import InjectionContext


class AttentionDriftInjector(PromptInjector):
    """注意力漂移注入器。"""

    def __init__(self, level: str = "subtle"):
        self.level = level  # "subtle" | "active" | "scattered" | "wild"

    @property
    def key(self) -> str:
        return "attention_drift"

    @property
    def priority(self) -> int:
        return 80

    async def build(self, context: InjectionContext) -> str:
        """读取 persona manager 当前 drift 档位 + locales 文案 + 锚点策略; 桩实现返回空。"""
        del context
        return ""
