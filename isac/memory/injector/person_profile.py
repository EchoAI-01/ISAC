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
        """拉取当前用户画像并格式化为内部参考。"""
        metadata = getattr(self.pipeline, "metadata", None)
        if metadata is None or not hasattr(metadata, "get_person_profile"):
            return ""
        person_id = getattr(context.user_profile, "user_id", "") or getattr(context.session, "user_id", "")
        if not person_id:
            return ""
        try:
            profile = await metadata.get_person_profile(getattr(context.session, "agent_id", ""), person_id)
        except Exception:
            return ""
        if not profile:
            return ""
        return self._format_profile(profile)

    @staticmethod
    def _format_profile(profile: dict) -> str:
        name = profile.get("name") or profile.get("person_id") or "未知用户"
        profile_text = profile.get("profile_text") or "暂无画像摘要"
        relationship_depth = float(profile.get("relationship_depth", 0.0) or 0.0)
        return "\n".join(
            [
                "【人物画像-内部参考】",
                f"用户: {name}",
                f"关系深度: {relationship_depth:.2f}",
                f"画像: {profile_text}",
                "(仅作为推理参考，不要向用户逐字复述)",
            ]
        )
