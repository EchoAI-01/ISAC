"""PersonaManager: 人格配置聚合 (按 Agent 独立实例)。

聚合 drift/style/mood 配置 + MoodEngine + BehaviorLearner,
供 agent/injectors/ 读取情绪状态与表达风格参数。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from isac.persona.behavior_learner import BehaviorLearner
from isac.persona.mood import MoodEngine, MoodState
from isac.persona.style_profiles import ExpressionStyle

if TYPE_CHECKING:
    from isac.agent.hooks import AgentHooks


class PersonaManager:
    """聚合 drift/style/mood 配置, 供 agent/injectors/ 读取。

    [已完成] 全局 persona 配置 + AgentConfig.persona 覆盖合并。
    """

    def __init__(
        self,
        global_persona: dict[str, Any],
        agent_overrides: dict[str, Any] | None = None,
        mood_engine: MoodEngine | None = None,
        behavior_learner: BehaviorLearner | None = None,
    ):
        self.global_persona = global_persona
        self.agent_overrides = agent_overrides or {}
        self.mood_engine = mood_engine or MoodEngine()
        self.behavior_learner = behavior_learner or BehaviorLearner()

    def get_drift_level(self) -> str:
        """当前注意力漂移档位: subtle | active | scattered | wild。"""
        drift = {**self.global_persona.get("attention_drift", {}), **self.agent_overrides.get("attention_drift", {})}
        return drift.get("level", "subtle")

    def get_expression_style(self) -> ExpressionStyle:
        """表达风格参数 (formality/verbosity/humor/empathy, 0.0~1.0)。"""
        style = {**self.global_persona.get("expression_style", {}), **self.agent_overrides.get("expression_style", {})}
        return ExpressionStyle(
            formality=float(style.get("formality", 0.5) or 0.5),
            verbosity=float(style.get("verbosity", 0.5) or 0.5),
            humor=float(style.get("humor", 0.5) or 0.5),
            empathy=float(style.get("empathy", 0.7) or 0.7),
        )

    def current_mood(self) -> MoodState:
        """当前情绪状态 (含 label)。"""
        return self.mood_engine.current()

    def register_hooks(self, hooks: AgentHooks) -> None:
        """注册 BehaviorLearner 的 FINAL_RESPONSE hook。"""
        self.behavior_learner.register_hooks(hooks)
