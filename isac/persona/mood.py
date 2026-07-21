"""情绪状态模型 (DEVELOPMENT_PLAN.md Day 29)。

职责: 情绪状态计算与转移。注入 Prompt 由 agent/injectors/mood.py 负责。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MoodState:
    """情绪状态"""

    valence: float = 0.0  # -1.0(负面) ~ 1.0(正面)
    arousal: float = 0.5  # 0.0(平静) ~ 1.0(激动)
    label: str = "neutral"


class MoodEngine:
    """情绪引擎 (按 Agent 独立实例)。

    TODO(Day 29): 根据对话内容/互动反馈更新 MoodState，随时间自然衰减回中性。
    """

    def __init__(self) -> None:
        self.state = MoodState()

    def current(self) -> MoodState:
        return self.state

    def update(self, valence_delta: float = 0.0, arousal_delta: float = 0.0) -> None:
        raise NotImplementedError("TODO(Day 29): 实现情绪更新与衰减")
