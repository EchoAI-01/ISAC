"""J2 模型路由器 (SPECIFICATION.md 2.4)。

``ModelRouter.select()`` 接收所需 operation、输入/输出模态、Agent 授权矩阵、成本上限、
延迟目标和健康状态, 返回可解释的 ``ModelSelection``; 业务层不得按模型名硬编码能力。

打分公式 (cost 越低分越高, latency 越快分越高, 健康加权, 偏好加分):
    score = (4 - cost_rank) * 2.0 + (2 - latency_rank) * 1.0 + health * 1.5 + pref * 0.5

cost_tier rank: free=0 < low=1 < standard=2 ≈ unknown=2 < high=3
latency_tier rank: fast=0 < standard=1 < slow=2

过滤链: 授权 → operation/模态 → cost_ceiling → latency_target → health (排除 unhealthy)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.provider.catalog import ModelSelection

if TYPE_CHECKING:
    from isac.provider.catalog import ModelCatalog, ModelDescriptor

# cost_tier 字符串 → rank (越大越贵). "unknown" 视为 standard=2 (保守不偏向).
_COST_TIER_RANK: dict[str, int] = {
    "free": 0,
    "low": 1,
    "standard": 2,
    "unknown": 2,
    "high": 3,
}

# latency_tier 字符串 → rank (越大越慢)
_LATENCY_TIER_RANK: dict[str, int] = {
    "fast": 0,
    "standard": 1,
    "slow": 2,
}


class ModelRouter:
    """按能力需求选择模型, 综合成本/延迟/健康/偏好打分排序。"""

    def __init__(self, catalog: ModelCatalog) -> None:
        self._catalog = catalog
        # 已知不健康的 provider_id 集合 (空集视为全健康, 不做过滤)
        self._unhealthy: set[str] = set()
        # 用户偏好的 provider_id 集合 (同分时加权胜出)
        self._preferences: set[str] = set()

    def record_health(self, provider_id: str, *, healthy: bool) -> None:
        """上报 provider 健康状态 (provider 调用失败/恢复时由 ProviderManager 调用)。

        空的 _unhealthy 集合表示"未观测到任何不健康", 此时 select() 不做 health 过滤;
        一旦有任意 record_health(False), 该 provider 会被排除, 其他仍视为健康。
        """
        if healthy:
            self._unhealthy.discard(provider_id)
        else:
            self._unhealthy.add(provider_id)

    def set_preference(self, provider_id: str) -> None:
        """标记用户偏好的 provider (同分时加权胜出)。"""
        self._preferences.add(provider_id)

    def clear_preference(self, provider_id: str) -> None:
        """清除偏好标记。"""
        self._preferences.discard(provider_id)

    def select(
        self,
        *,
        operation: str,
        modalities_in: set[str] | None = None,
        modalities_out: set[str] | None = None,
        allowed_operations: set[str] | None = None,
        cost_ceiling: str | None = None,
        latency_target: str | None = None,
    ) -> ModelSelection | None:
        """选择满足 operation/模态/授权/成本/延迟/健康的最高分模型; 无候选返回 None。"""
        # 1. Agent 授权: 未授权该 operation 直接无候选
        if allowed_operations is not None and operation not in allowed_operations:
            return None

        # 2. operation + 模态过滤
        candidates = self._catalog.find_by_operation(operation)
        if modalities_in:
            candidates = [d for d in candidates if modalities_in <= d.modalities_in]
        if modalities_out:
            candidates = [d for d in candidates if modalities_out <= d.modalities_out]
        if not candidates:
            return None

        # 3. cost_ceiling 过滤: cost_rank 超过 ceiling_rank 的候选排除
        if cost_ceiling is not None:
            ceiling_rank = _COST_TIER_RANK.get(cost_ceiling, 999)
            candidates = [
                d for d in candidates
                if _COST_TIER_RANK.get(d.cost_tier, 2) <= ceiling_rank
            ]

        # 4. latency_target 过滤: latency_rank 超过 target_rank 的候选排除
        if latency_target is not None:
            target_rank = _LATENCY_TIER_RANK.get(latency_target, 999)
            candidates = [
                d for d in candidates
                if _LATENCY_TIER_RANK.get(d.latency_tier, 1) <= target_rank
            ]

        # 5. health 过滤: 已知不健康的 provider 排除 (空 _unhealthy 时不过滤)
        if self._unhealthy:
            candidates = [d for d in candidates if d.provider_id not in self._unhealthy]

        if not candidates:
            return None

        # 6. 打分排序, 取最高分 (同分时偏好加权; 仍同分则取列表第一个, 稳定)
        scored = sorted(
            candidates,
            key=lambda d: self._score(d),
            reverse=True,
        )
        best = scored[0]
        best_score = self._score(best)
        reason = self._explain(best, best_score, operation, cost_ceiling, latency_target)
        return ModelSelection(descriptor=best, reason=reason, fallback_used=False)

    def _score(self, d: ModelDescriptor) -> float:
        cost_rank = _COST_TIER_RANK.get(d.cost_tier, 2)
        latency_rank = _LATENCY_TIER_RANK.get(d.latency_tier, 1)
        health = 0.0 if d.provider_id in self._unhealthy else 1.0
        pref = 1.0 if d.provider_id in self._preferences else 0.0
        return (4 - cost_rank) * 2.0 + (2 - latency_rank) * 1.0 + health * 1.5 + pref * 0.5

    def _explain(
        self,
        d: ModelDescriptor,
        score: float,
        operation: str,
        cost_ceiling: str | None,
        latency_target: str | None,
    ) -> str:
        healthy = "unhealthy" if d.provider_id in self._unhealthy else "healthy"
        preferred = ", preferred" if d.provider_id in self._preferences else ""
        cost_str = (
            f"cost_tier={d.cost_tier}(ceiling={cost_ceiling})"
            if cost_ceiling
            else f"cost_tier={d.cost_tier}"
        )
        latency_str = (
            f"latency_tier={d.latency_tier}(target={latency_target})"
            if latency_target
            else f"latency_tier={d.latency_tier}"
        )
        return (
            f"operation={operation}, score={score:.2f}, "
            f"{cost_str}, {latency_str}, health={healthy}{preferred}"
        )
