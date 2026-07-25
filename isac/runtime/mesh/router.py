"""MeshRouter: observer/candidate 路由骨架 (M1, ROUTING_AND_AGENT_MESH.md §2)。

[框架已搭建 / scaffolding] 把既有 `RoutingDecision` 包成带旁听/候选角色的
`MeshRoutingDecision` 的挂接点就位;真正的候选仲裁 (多 Agent 竞争同一消息选回复者)、
observer 记忆旁路、决策可解释与审计留待 M1 实现节点 (见 TODO)。默认只返回主处理者 +
空 observer/candidate, 与现有单主路由零行为变化。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.runtime.mesh.models import MeshRoutingDecision
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.router.types import RoutingDecision

logger = get_logger(__name__)


class MeshRouter:
    """在基础路由之上叠加 observer/candidate 角色 (骨架)。"""

    def to_mesh_decision(self, base: RoutingDecision) -> MeshRoutingDecision:
        """把基础 `RoutingDecision` 提升为 `MeshRoutingDecision`。

        TODO(M1): 结合 Agent 角色配置 (primary/observer/candidate) 填充
        observer_agent_ids / candidate_agent_ids, 并对多候选做仲裁。
        骨架阶段: 只搬运主处理者, observer/candidate 恒空 = 单主路由不变。
        """
        return MeshRoutingDecision(
            primary_agent_id=base.agent_id,
            matched_by=base.matched_by,
            content=base.content,
        )

    def arbitrate(self, decision: MeshRoutingDecision) -> str | None:
        """从候选者中仲裁出实际回复者; 无候选时返回主处理者。

        TODO(M1): 按门控分/关系/专注度仲裁; 骨架阶段直接返回 primary。
        """
        return decision.primary_agent_id
