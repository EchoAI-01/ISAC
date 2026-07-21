"""core/injector 单元测试：验证 PromptInjector 基类已下沉到 core，
避免 memory/ 直接依赖 agent/ 造成导入环。
"""

from __future__ import annotations

from isac.core.injector import PromptInjector
from isac.core.types import InjectionContext


class DummyInjector(PromptInjector):
    @property
    def key(self) -> str:
        return "dummy"

    async def build(self, context: InjectionContext) -> str:
        return "dummy"


def test_prompt_injector_importable_from_core():
    injector = DummyInjector()
    assert injector.key == "dummy"
    assert injector.priority == 50
    assert injector.tokens_estimate == 200
