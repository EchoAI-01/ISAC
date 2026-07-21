"""PersonProfileInjector: 人物画像注入 (每轮, ARCHITECTURE.md 3.6)。"""

from __future__ import annotations

from isac.core.types import InjectionContext
from isac.memory.injector.base import MemoryInjector
from isac.memory.pipeline import MemoryRetrievalPipeline


class PersonProfileInjector(MemoryInjector):
    """识别对话参与者 → 拉取画像 → 【人物画像-内部参考】格式注入。"""

    def __init__(self, pipeline: MemoryRetrievalPipeline, max_profiles: int = 3):
        super().__init__(pipeline)
        self.max_profiles = max_profiles

    @property
    def key(self) -> str:
        return "person_profile"

    @property
    def priority(self) -> int:
        return 70

    @property
    def tokens_estimate(self) -> int:
        return 400

    async def build(self, context: InjectionContext) -> str:
        """TODO(Day 24): 识别参与者 → MetadataStore.get_person_profile → 格式化。"""
        return ""
