"""门控类型定义。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GateKind(Enum):
    TRIGGER = "trigger"  # 立即进入 Agent Loop
    WAIT = "wait"  # 不回复，继续积攒消息
    DELAY = "delay"  # 延迟 N 秒后再评估


@dataclass
class GateDecision:
    """门控决策结果"""

    kind: GateKind
    delay_seconds: float = 0.0

    @classmethod
    def trigger(cls) -> GateDecision:
        return cls(kind=GateKind.TRIGGER)

    @classmethod
    def wait(cls) -> GateDecision:
        return cls(kind=GateKind.WAIT)

    @classmethod
    def delay(cls, seconds: float) -> GateDecision:
        return cls(kind=GateKind.DELAY, delay_seconds=seconds)
