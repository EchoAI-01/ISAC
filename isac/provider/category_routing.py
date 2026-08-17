"""U7 category 路由: 委派任务按类型选模型链, 并入 ModelCatalog/ModelRouter 数据驱动路由。

四类任务画像 (``CATEGORY_PROFILES``, 可经 ``config.model_routing.categories`` 覆盖,
数据驱动不改代码):
- ``qa`` 问答: 快 + 便宜;
- ``creative`` 创作: 质量优先, 放宽成本上限;
- ``tool_heavy`` 工具密集: 必须 supports_tools;
- ``chat`` 闲聊: 最便宜档。

选择经既有 ModelRouter (能力/成本/延迟/健康过滤 + 打分), 无候选返回 None ——
调用方回落父 Agent 模型 (fail-safe 零行为变化)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from isac.provider.router import ModelRouter
from isac.utils.logger import get_logger

logger = get_logger(__name__)

VALID_CATEGORIES = frozenset({"qa", "creative", "tool_heavy", "chat"})


@dataclass(frozen=True)
class CategoryProfile:
    """一类任务对模型的需求画像 (ModelRouter.select 的过滤参数)。"""

    operation: str = "chat"
    cost_ceiling: str | None = None  # free|low|standard|high; None = 不限
    latency_target: str | None = None  # fast|standard|slow; None = 不限
    requires_tools: bool = False
    modalities_in: frozenset[str] = frozenset()


# 默认画像 (config.model_routing.categories 可按键覆盖同名字段)
CATEGORY_PROFILES: dict[str, CategoryProfile] = {
    "qa": CategoryProfile(cost_ceiling="standard", latency_target="fast"),
    "creative": CategoryProfile(cost_ceiling="high"),
    "tool_heavy": CategoryProfile(requires_tools=True),
    "chat": CategoryProfile(cost_ceiling="low", latency_target="fast"),
}


def profile_for(category: str, config: dict[str, Any] | None = None) -> CategoryProfile | None:
    """取 category 画像 (config 覆盖优先); 未知 category 返回 None。"""
    category = str(category or "").strip().lower()
    if category not in VALID_CATEGORIES:
        return None
    base = CATEGORY_PROFILES[category]
    overrides = (config or {}).get(category)
    if not isinstance(overrides, dict):
        return base
    kwargs: dict[str, Any] = {
        "operation": base.operation,
        "cost_ceiling": base.cost_ceiling,
        "latency_target": base.latency_target,
        "requires_tools": base.requires_tools,
        "modalities_in": base.modalities_in,
    }
    for key in ("operation", "cost_ceiling", "latency_target", "requires_tools"):
        if key in overrides:
            kwargs[key] = overrides[key]
    return CategoryProfile(**kwargs)


def select_for_category(
    router: ModelRouter,
    category: str,
    *,
    config: dict[str, Any] | None = None,
    allowed_operations: set[str] | None = None,
) -> Any:
    """按 category 经 ModelRouter 选模型; 无画像/无候选返回 None (调用方回落)。"""
    profile = profile_for(category, config)
    if profile is None:
        logger.debug("category 未知, 不做路由", category=category)
        return None
    selection = router.select(
        operation=profile.operation,
        modalities_in=set(profile.modalities_in) or None,
        allowed_operations=allowed_operations,
        cost_ceiling=profile.cost_ceiling,
        latency_target=profile.latency_target,
        requires_tools=profile.requires_tools,
    )
    return selection
