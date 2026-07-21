"""base_identity 注入器: Bot 基础身份。"""

from __future__ import annotations

from isac.core.injector import PromptInjector
from isac.core.types import InjectionContext
from isac.locales import load_text


class BaseIdentityInjector(PromptInjector):
    """注入 Bot 的基础身份定义 (最高优先级)。"""

    def __init__(self, identity_text: str | None = None):
        self._identity_text = identity_text

    @property
    def key(self) -> str:
        return "base_identity"

    @property
    def priority(self) -> int:
        return 100  # 最先注入

    @property
    def tokens_estimate(self) -> int:
        return 100

    async def build(self, context: InjectionContext) -> str:
        return self._identity_text or load_text("base_identity")
