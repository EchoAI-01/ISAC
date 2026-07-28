"""mood 注入器: 情绪状态注入 (Q2 激活)。

persona/mood.py 负责情绪状态计算 (MoodEngine + MoodState), 本注入器负责把当前
情绪状态读出并注入 Prompt, 让 LLM 在回复时带出对应的情绪色彩 (开心/烦躁/平静/
激动等)。PersonaManager 注入 MoodEngine; 无 MoodEngine 时返回空串 (零行为变化,
不影响主链路)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.core.injector import PromptInjector
from isac.core.types import InjectionContext
from isac.locales import load_text

if TYPE_CHECKING:
    from isac.persona.mood import MoodEngine, MoodState

# mood label → i18n key 的映射; 每个离散情绪一段对应的提示文案
_MOOD_LABEL_KEYS: dict[str, str] = {
    "excited": "mood.excited",
    "happy": "mood.happy",
    "calm": "mood.calm",
    "angry": "mood.angry",
    "sad": "mood.sad",
    "upset": "mood.upset",
    "tense": "mood.tense",
    "bored": "mood.bored",
    "neutral": "mood.neutral",
}


class MoodInjector(PromptInjector):
    """情绪状态注入器 (Q2 激活)。"""

    def __init__(self, mood_engine: MoodEngine | None = None):
        self._mood_engine = mood_engine

    @property
    def key(self) -> str:
        return "mood_system"

    @property
    def priority(self) -> int:
        return 70

    async def build(self, context: InjectionContext) -> str:
        """读取 MoodEngine 当前情绪 → 生成情绪提示文案; 无 MoodEngine 时返回空。"""
        del context
        if self._mood_engine is None:
            return ""
        mood = self._mood_engine.current()
        return _render_mood_prompt(mood)


def _render_mood_prompt(mood: MoodState) -> str:
    """把 MoodState 转成 Prompt 提示文案。"""
    key = _MOOD_LABEL_KEYS.get(mood.label, "mood.neutral")
    text = load_text(key)
    # 在 i18n 文案后附 valence/arousal 数值, 让 LLM 有量化参考 (i18n 文案是
    # 主提示, 数值是补充; 若 i18n key 缺失 fallback 到 key 字符串, 数值仍
    # 有意义)。
    return (
        f"【当前情绪状态】\n"
        f"- 情绪: {mood.label} ({text})\n"
        f"- 效价(valence): {mood.valence:+.2f} (负=负面, 正=正面)\n"
        f"- 激活(arousal): {mood.arousal:.2f} (低=平静, 高=激动)\n"
        f"请让回复自然带出此情绪色彩, 不要直白说出情绪数值。"
    )
