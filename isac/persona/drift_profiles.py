"""注意力漂移配置 (DEVELOPMENT_PLAN.md Day 28)。

文案经 locales 获取 (ADR-006)，此处只定义档位元数据。
"""

from __future__ import annotations

DRIFT_LEVELS = ("subtle", "active", "scattered", "wild")

# 档位 → locales key 与锚点策略默认值
DRIFT_PROFILES: dict[str, dict] = {
    "subtle": {"text_key": "attention_drift.subtle", "anchor_policy": "strict"},
    "active": {"text_key": "attention_drift.active", "anchor_policy": "balanced"},
    "scattered": {"text_key": "attention_drift.scattered", "anchor_policy": "loose"},
    "wild": {"text_key": "attention_drift.wild", "anchor_policy": "loose"},
}
