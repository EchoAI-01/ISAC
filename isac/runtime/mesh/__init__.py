"""Agent Mesh 深化 (M 节点, ROUTING_AND_AGENT_MESH.md)。

[框架已搭建 / scaffolding] 契约 (MeshRoutingDecision/RoutingRole/MeshLinkPolicy/
MeshMessageType) + MeshRouter (M1 observer/candidate) + MeshActionBroker (M2
handoff/notify/memory_query) 骨架就位。为不破坏 `**dict` 构造的既有
`router.types.RoutingDecision` / `runtime.bus.InterAgentLink`, 采用新增 sibling 契约。
默认不接入主链路, 单主路由 + deny-by-default 动作, 主链路零行为变化。
业务实现见 DEVELOPMENT_PLAN.md §四 M 节点。
"""

from __future__ import annotations

from isac.runtime.mesh.actions import MeshActionBroker
from isac.runtime.mesh.models import (
    MeshLinkPolicy,
    MeshMessageType,
    MeshRoutingDecision,
    RoutingRole,
)
from isac.runtime.mesh.router import MeshRouter

__all__ = [
    "MeshActionBroker",
    "MeshLinkPolicy",
    "MeshMessageType",
    "MeshRouter",
    "MeshRoutingDecision",
    "RoutingRole",
]
