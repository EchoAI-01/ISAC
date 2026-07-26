"""MeshRouter: observer/candidate 路由 (M1, ROUTING_AND_AGENT_MESH.md §2)。

M1 实现: to_mesh_decision 按 AgentConfig.mesh_role 填充 observer/candidate;
arbitrate 多候选按 gating_score 降序仲裁 (取最高, 但低于 primary 时返回 primary);
observer 不参与仲裁 (只观察); 决策可解释 (decision.reason 记录仲裁过程)。
默认无角色配置时 observer/candidate 为空 = 单主路由 (零行为变化)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.runtime.mesh.models import MeshRoutingDecision, RoutingRole
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.router.types import RoutingDecision

logger = get_logger(__name__)


class MeshRouter:
    """在基础路由之上叠加 observer/candidate 角色。"""

    def __init__(self, *, agent_roles: dict[str, str] | None = None) -> None:
        """agent_roles: agent_id → "primary"/"observer"/"candidate"; 默认 None = 无角色配置."""
        self._agent_roles: dict[str, str] = agent_roles or {}

    def to_mesh_decision(self, base: RoutingDecision) -> MeshRoutingDecision:
        """把基础 `RoutingDecision` 提升为 `MeshRoutingDecision`。

        M1: 遍历 agent_roles, 把 observer 加入 observer_agent_ids,
        candidate 加入 candidate_agent_ids, primary 不动 (由 base.agent_id 决定)。
        无角色配置时 observer/candidate 为空 = 单主路由。
        """
        observer_ids: list[str] = []
        candidate_ids: list[str] = []
        for agent_id, role_str in self._agent_roles.items():
            # 跳过 primary (主处理者已在 base.agent_id)
            if agent_id == base.agent_id:
                continue
            try:
                role = RoutingRole(role_str)
            except ValueError:
                # 未知角色字符串跳过 (保守, 不误归类)
                continue
            if role is RoutingRole.OBSERVER:
                observer_ids.append(agent_id)
            elif role is RoutingRole.CANDIDATE:
                candidate_ids.append(agent_id)
        return MeshRoutingDecision(
            primary_agent_id=base.agent_id,
            matched_by=base.matched_by,
            content=base.content,
            observer_agent_ids=observer_ids,
            candidate_agent_ids=candidate_ids,
        )

    def arbitrate(
        self,
        decision: MeshRoutingDecision,
        *,
        gating_scores: dict[str, float] | None = None,
    ) -> str | None:
        """从候选者中仲裁出实际回复者; 无候选/分数缺失时返回 primary。

        M1: 多候选按 gating_score 降序, 取最高者; 但需**显著高于** primary
        (差值 > SWITCH_MARGIN=0.3) 才切换, 避免小噪声触发抖动; 否则返回 primary。
        observer 不参与仲裁。decision.reason 记录仲裁结果供审计。
        """
        primary = decision.primary_agent_id
        if not decision.candidate_agent_ids or gating_scores is None:
            decision.reason = "no-candidates-or-scores: returning primary"
            return primary
        # primary 分数默认 0 (保守基线)
        primary_score = float(gating_scores.get(primary or "", 0.0))
        best_candidate: str | None = None
        best_score = -1.0
        for cand in decision.candidate_agent_ids:
            score = float(gating_scores.get(cand, 0.0))
            if score > best_score:
                best_score = score
                best_candidate = cand
        if best_candidate is None or (best_score - primary_score) <= SWITCH_MARGIN:
            decision.reason = (
                f"arbitration: best_candidate={best_candidate} score={best_score:.3f} "
                f"not significantly higher than primary={primary} score={primary_score:.3f} "
                f"(margin={SWITCH_MARGIN}); keeping primary"
            )
            return primary
        decision.reason = (
            f"arbitration: best_candidate={best_candidate} score={best_score:.3f} "
            f"significantly higher than primary={primary} score={primary_score:.3f} "
            f"(margin={SWITCH_MARGIN}); switching to candidate"
        )
        logger.info(
            "Mesh 仲裁切换",
            primary=primary,
            winner=best_candidate,
            primary_score=round(primary_score, 3),
            best_score=round(best_score, 3),
        )
        return best_candidate


# 候选切换所需的最小分数差 (避免小噪声触发抖动)
SWITCH_MARGIN: float = 0.3
