"""attention_drift 注入器: 注意力漂移人格 (ARCHITECTURE.md 3.4, Q2 激活)。

读取 persona/drift_profiles 配置, 通过 locales 获取本地化漂移文案 (ADR-006),
注入 Prompt 让 LLM 在回复时按对应档位 (subtle/active/scattered/wild) 自然带出
注意力漂移特征——像真人一样在相关话题间联想, 而非机械问答。
"""

from __future__ import annotations

from isac.core.injector import PromptInjector
from isac.core.types import InjectionContext
from isac.locales import load_text
from isac.persona.drift_profiles import DRIFT_PROFILES


class AttentionDriftInjector(PromptInjector):
    """注意力漂移注入器 (Q2 激活)。"""

    def __init__(self, level: str = "subtle"):
        self.level = level  # "subtle" | "active" | "scattered" | "wild"

    @property
    def key(self) -> str:
        return "attention_drift"

    @property
    def priority(self) -> int:
        return 80

    async def build(self, context: InjectionContext) -> str:
        """读取 drift 档位 + locales 文案 + 锚点策略 → 注入提示文案。"""
        del context
        profile = DRIFT_PROFILES.get(self.level) or DRIFT_PROFILES["subtle"]
        text = load_text(profile["text_key"])
        anchor_policy = profile.get("anchor_policy", "balanced")
        anchor_text = _ANCHOR_POLICY_TEXT.get(anchor_policy, "")
        return (
            f"【注意力漂移人格】\n"
            f"- 档位: {self.level}\n"
            f"- {text}\n"
            f"- 锚点策略: {anchor_policy} ({anchor_text})"
        )


# 锚点策略说明: 漂移后的回归强度
_ANCHOR_POLICY_TEXT: dict[str, str] = {
    "strict": "漂移后尽快回归原话题",
    "balanced": "漂移后适度展开再回归",
    "loose": "漂移后可充分展开",
}
