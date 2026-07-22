"""表达风格配置。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExpressionStyle:
    """表达风格参数 (SPECIFICATION.md 3.1 persona.expression_style)"""

    formality: float = 0.5  # 0.0=随意 ~ 1.0=正式
    verbosity: float = 0.5  # 0.0=简洁 ~ 1.0=详尽
    humor: float = 0.5  # 0.0=严肃 ~ 1.0=幽默
    empathy: float = 0.7  # 0.0=理性 ~ 1.0=感性


DEFAULT_STYLE = ExpressionStyle()
