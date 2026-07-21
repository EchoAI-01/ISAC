"""PersonaManager: 人格配置聚合 (按 Agent 独立实例)。"""

from __future__ import annotations

from typing import Any


class PersonaManager:
    """聚合 drift/style/mood 配置，供 agent/injectors/ 读取。

    TODO(Day 29): 全局 persona 配置 + AgentConfig.persona 覆盖合并。
    """

    def __init__(self, global_persona: dict[str, Any], agent_overrides: dict[str, Any] | None = None):
        self.global_persona = global_persona
        self.agent_overrides = agent_overrides or {}

    def get_drift_level(self) -> str:
        """当前注意力漂移档位: subtle | active | scattered | wild。"""
        drift = {**self.global_persona.get("attention_drift", {}), **self.agent_overrides.get("attention_drift", {})}
        return drift.get("level", "subtle")

    def get_expression_style(self) -> dict[str, float]:
        """表达风格参数 (formality/verbosity/humor/empathy, 0.0~1.0)。"""
        style = {**self.global_persona.get("expression_style", {}), **self.agent_overrides.get("expression_style", {})}
        return {
            "formality": style.get("formality", 0.5),
            "verbosity": style.get("verbosity", 0.5),
            "humor": style.get("humor", 0.5),
            "empathy": style.get("empathy", 0.7),
        }
