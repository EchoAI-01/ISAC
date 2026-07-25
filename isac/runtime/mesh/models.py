"""Agent Mesh 数据契约 (M 节点, ROUTING_AND_AGENT_MESH.md §2/§5/§6)。

拟人化多 Agent 协作层的值对象: 路由角色、Mesh 路由结果、Link 策略、Agent 间消息
类型。均为纯数据、不含行为; 行为在 router.py / actions.py。字段严格对齐专项设计文档。

[框架已搭建 / scaffolding] 契约就位; observer/candidate 仲裁 (M1)、
handoff/notify/memory_query 真实投递 (M2) 留待实现节点。为避免破坏 `**dict` 构造的
既有 `router.types.RoutingDecision` / `runtime.bus.InterAgentLink`, 本模块新增 sibling
契约而非改动既有类。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RoutingRole(StrEnum):
    """某 Agent 对一条消息的路由角色 (ROUTING_AND_AGENT_MESH.md §2)。"""

    PRIMARY = "primary"  # 主处理者, 产出回复
    OBSERVER = "observer"  # 旁听, 只入记忆不回复
    CANDIDATE = "candidate"  # 候选, 可被仲裁选为回复者 / 供 handoff·ask


class MeshMessageType(StrEnum):
    """Agent 间消息类型 (ROUTING_AND_AGENT_MESH.md §5.1)。

    既有 `runtime.bus.InterAgentMessage.type` 是自由字符串, 本枚举提供受控取值,
    M2 落地时用它替换裸字符串, 不改 bus 契约。
    """

    REQUEST = "request"
    RESPONSE = "response"
    NOTIFY = "notify"
    HANDOFF = "handoff"
    MEMORY_QUERY = "memory_query"


@dataclass
class MeshRoutingDecision:
    """Mesh 路由结果 (ROUTING_AND_AGENT_MESH.md §2)。

    在既有 `RoutingDecision` (agent_id/matched_by/content) 之外补充旁听者与候选者;
    M1 落地时由 MeshRouter 产出。默认 observer/candidate 为空 = 退化为单主处理者,
    与现有路由行为一致。
    """

    primary_agent_id: str | None
    matched_by: str  # binding | trigger_word | command | default | hook | drop
    content: str
    observer_agent_ids: list[str] = field(default_factory=list)
    candidate_agent_ids: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class MeshLinkPolicy:
    """Link 的动作与可见范围策略 (ROUTING_AND_AGENT_MESH.md §6.1)。

    既有 `InterAgentLink` 只有 from/to/direction/enabled; 本策略补充权限动作、
    可见记忆范围、上下文消息上限。M2 落地时与 Link 组合做 ACL 校验, 不改 Link 契约。
    """

    permissions: list[str] = field(default_factory=list)  # ask|notify|handoff|memory_query
    visible_memory_scopes: list[str] = field(default_factory=list)
    max_context_messages: int = 20
