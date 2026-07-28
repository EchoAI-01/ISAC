"""expression_style 注入器: 表达风格人格 (Q2 激活)。

读取 PersonaManager.get_expression_style() (合并全局 + Agent override) +
UserProfile.expression_style 覆盖 (用户个性化偏好), 生成表达风格指令注入
Prompt, 让 LLM 回复的正式度/详尽度/幽默/共情度符合该 Agent + 该用户的风格。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.core.injector import PromptInjector
from isac.core.types import InjectionContext
from isac.persona.style_profiles import ExpressionStyle

if TYPE_CHECKING:
    from isac.persona.manager import PersonaManager


class ExpressionStyleInjector(PromptInjector):
    """表达风格注入器 (正式度/详尽度/幽默/共情, SPECIFICATION.md 3.1 persona)。"""

    def __init__(self, persona_manager: PersonaManager | None = None):
        self._persona = persona_manager

    @property
    def key(self) -> str:
        return "expression_style"

    @property
    def priority(self) -> int:
        return 80

    async def build(self, context: InjectionContext) -> str:
        """读取 persona manager 表达风格 + UserProfile 覆盖 → 生成风格指令;
        无 persona manager 时返回空串 (零行为变化)。"""
        if self._persona is None:
            return ""
        base = self._persona.get_expression_style()
        # UserProfile.expression_style 是 dict, 可能含与用户偏好相关的覆盖
        # (如某用户偏好更简洁); 与全局/Agent 风格取算术平均 (用户侧权重 50%)。
        profile = context.user_profile
        if profile is not None and profile.expression_style:
            style = _merge_style_with_user(base, profile.expression_style)
        else:
            style = base
        return _render_style_prompt(style)


def _merge_style_with_user(base: ExpressionStyle, user_override: dict) -> ExpressionStyle:
    """用户偏好与全局风格按 50/50 权重合并 (用户侧覆盖全局倾向)。"""
    try:
        return ExpressionStyle(
            formality=(base.formality + float(user_override.get("formality", base.formality) or base.formality)) / 2,
            verbosity=(base.verbosity + float(user_override.get("verbosity", base.verbosity) or base.verbosity)) / 2,
            humor=(base.humor + float(user_override.get("humor", base.humor) or base.humor)) / 2,
            empathy=(base.empathy + float(user_override.get("empathy", base.empathy) or base.empathy)) / 2,
        )
    except (TypeError, ValueError):
        return base


def _render_style(style: ExpressionStyle, axis: str, low: str, high: str) -> str:
    """0.0~1.0 的单轴值 → 倾向文案 (低/中/高三段)。"""
    value = getattr(style, axis)
    if value <= 0.33:
        return low
    if value >= 0.67:
        return high
    return f"介于{low}与{high}之间"


def _render_style_prompt(style: ExpressionStyle) -> str:
    """把 ExpressionStyle 转成 Prompt 提示文案。"""
    formality_text = _render_style(style, "formality", "随意口语", "正式严谨")
    verbosity_text = _render_style(style, "verbosity", "简洁精炼", "详尽展开")
    humor_text = _render_style(style, "humor", "严肃", "幽默")
    empathy_text = _render_style(style, "empathy", "理性客观", "感性共情")
    return (
        f"【表达风格】\n"
        f"- 正式度: {formality_text} ({style.formality:.2f})\n"
        f"- 详尽度: {verbosity_text} ({style.verbosity:.2f})\n"
        f"- 幽默度: {humor_text} ({style.humor:.2f})\n"
        f"- 共情度: {empathy_text} ({style.empathy:.2f})\n"
        f"请按此风格调整回复, 数值仅作参考不要直白引用。"
    )
