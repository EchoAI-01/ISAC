"""情绪状态模型 (ARCHITECTURE.md 3.8)。

职责: 情绪状态计算与转移。注入 Prompt 由 agent/injectors/mood.py 负责。

MoodEngine 维护一个 MoodState (valence / arousal / label)。
- update(): 根据 valence_delta / arousal_delta 累计情绪, 钳制到 [-1,1] / [0,1]。
- decay(): 自然衰减回中性, 每次调用按 decay_rate 衰减一半。
- label: 由 (valence, arousal) 二维映射到离散情绪标签 (开心/平静/烦躁/激动/中性)。
"""

from __future__ import annotations

from dataclasses import dataclass

VALENCE_POSITIVE_THRESHOLD = 0.2
VALENCE_NEGATIVE_THRESHOLD = -0.2
AROUSAL_HIGH_THRESHOLD = 0.7
AROUSAL_LOW_THRESHOLD = 0.3


@dataclass
class MoodState:
    """情绪状态"""

    valence: float = 0.0  # -1.0(负面) ~ 1.0(正面)
    arousal: float = 0.5  # 0.0(平静) ~ 1.0(激动)
    label: str = "neutral"

    def with_label(self) -> MoodState:
        """根据 valence/arousal 重新计算 label。"""
        return MoodState(
            valence=self.valence,
            arousal=self.arousal,
            label=_label_for(self.valence, self.arousal),
        )


def _label_for(valence: float, arousal: float) -> str:
    """(valence, arousal) → 离散情绪标签。"""
    if valence > VALENCE_POSITIVE_THRESHOLD:
        if arousal > AROUSAL_HIGH_THRESHOLD:
            return "excited"
        if arousal < AROUSAL_LOW_THRESHOLD:
            return "calm"
        return "happy"
    if valence < VALENCE_NEGATIVE_THRESHOLD:
        if arousal > AROUSAL_HIGH_THRESHOLD:
            return "angry"
        if arousal < AROUSAL_LOW_THRESHOLD:
            return "sad"
        return "upset"
    if arousal > AROUSAL_HIGH_THRESHOLD:
        return "tense"
    if arousal < AROUSAL_LOW_THRESHOLD:
        return "bored"
    return "neutral"


class MoodEngine:
    """情绪引擎 (按 Agent 独立实例)。

    情绪更新后向中性方向衰减: update 与 decay 都会重新计算 label。
    衰减策略: valence 按比例靠近 0, arousal 按比例靠近 0.5 (中性)。
    """

    def __init__(self, decay_rate: float = 0.05) -> None:
        """Args:
            decay_rate: 每次衰减移动到中性的比例, 默认 5%。
        """
        self.state = MoodState()
        self.decay_rate = max(0.0, min(1.0, decay_rate))

    def current(self) -> MoodState:
        return self.state

    def update(self, valence_delta: float = 0.0, arousal_delta: float = 0.0) -> MoodState:
        """累计情绪变化, 钳制并刷新 label。

        valence 钳到 [-1, 1], arousal 钳到 [0, 1]。
        """
        self.state.valence = max(-1.0, min(1.0, self.state.valence + valence_delta))
        self.state.arousal = max(0.0, min(1.0, self.state.arousal + arousal_delta))
        self.state = self.state.with_label()
        return self.state

    def decay(self) -> MoodState:
        """情绪向中性自然衰减。"""
        if self.decay_rate <= 0:
            self.state = self.state.with_label()
            return self.state
        self.state.valence = self.state.valence * (1.0 - self.decay_rate)
        # arousal 中性 = 0.5
        self.state.arousal = 0.5 + (self.state.arousal - 0.5) * (1.0 - self.decay_rate)
        self.state = self.state.with_label()
        return self.state

    def reset(self) -> None:
        """重置为中性 (用于会话切换或测试)。"""
        self.state = MoodState()
