"""Agent Mesh (M1/M2) 骨架测试 (M1/M2 已实现后的回归)。

验证 M1 (MeshRoutingDecision/MeshRouter observer/candidate + arbitrate) 与
M2 (MeshActionBroker ACL + bus 投递 + A2A 工具 restricted) 的契约与行为,
并断言既有 RoutingDecision / InterAgentLink 契约字段未被改动 (approach b)。
详细业务测试在 test_mesh_router.py / test_mesh_actions.py。
"""

from __future__ import annotations

import dataclasses

from isac.agent.tools.base import ToolPermission
from isac.router.types import RoutingDecision
from isac.runtime.bus import InterAgentLink
from isac.runtime.mesh import (
    MeshActionBroker,
    MeshLinkPolicy,
    MeshMessageType,
    MeshRouter,
    MeshRoutingDecision,
    RoutingRole,
)

# ── M1: 契约 + MeshRouter ────────────────────────────────────────


def test_routing_role_and_message_type_values() -> None:
    assert set(RoutingRole) == {RoutingRole.PRIMARY, RoutingRole.OBSERVER, RoutingRole.CANDIDATE}
    assert MeshMessageType.MEMORY_QUERY.value == "memory_query"
    assert {m.value for m in MeshMessageType} == {"request", "response", "notify", "handoff", "memory_query"}


def test_mesh_routing_decision_defaults_empty_observer_candidate() -> None:
    d = MeshRoutingDecision(primary_agent_id="a1", matched_by="binding", content="hi")
    assert d.observer_agent_ids == []
    assert d.candidate_agent_ids == []
    assert d.reason == ""


def test_mesh_router_wraps_base_decision_primary_only() -> None:
    base = RoutingDecision(agent_id="a1", matched_by="trigger_word", content="hello")
    mesh = MeshRouter().to_mesh_decision(base)
    assert mesh.primary_agent_id == "a1"
    assert mesh.matched_by == "trigger_word"
    assert mesh.content == "hello"
    assert mesh.observer_agent_ids == [] and mesh.candidate_agent_ids == []  # 单主路由不变


def test_mesh_router_arbitrate_returns_primary_when_no_candidate() -> None:
    d = MeshRoutingDecision(primary_agent_id="a1", matched_by="default", content="")
    assert MeshRouter().arbitrate(d) == "a1"


# ── M2: MeshActionBroker deny-by-default + bus 投递 ─────────────


def test_action_broker_deny_by_default_without_policy() -> None:
    broker = MeshActionBroker()
    assert broker.is_permitted("notify", None) is False


def test_action_broker_permits_only_listed_actions() -> None:
    broker = MeshActionBroker()
    policy = MeshLinkPolicy(permissions=["notify"])
    assert broker.is_permitted("notify", policy) is True
    assert broker.is_permitted("handoff", policy) is False


async def test_action_broker_async_actions_respect_policy_and_bus() -> None:
    """M2: ACL 不通过或无 bus 时拒绝; ACL 通过且有 bus 时投递成功."""
    from isac.runtime.bus import InterAgentBus, InterAgentLink

    broker = MeshActionBroker()
    # 无 bus: 所有动作拒绝 (零行为变化)
    assert await broker.notify("a1", "a2", "hi", None) is False
    # policy 含 handoff 但无 bus: 仍拒绝
    assert await broker.handoff("a1", "a2", "s", MeshLinkPolicy(permissions=["handoff"])) is False
    assert broker.list_available("a1") == []
    # 有 bus + Link + policy: handoff 投递成功
    bus = InterAgentBus()
    bus.add_link(InterAgentLink(from_agent="a1", to_agent="a2"))
    broker2 = MeshActionBroker(bus)
    ok = await broker2.handoff("a1", "a2", "s", MeshLinkPolicy(permissions=["handoff"]))
    assert ok is True


def test_mesh_link_policy_defaults() -> None:
    p = MeshLinkPolicy()
    assert p.permissions == [] and p.visible_memory_scopes == []
    assert p.max_context_messages == 20


# ── A2A 工具 restricted (M2 已接入 broker, 需注入方可调用) ───────


def test_a2a_tools_restricted_after_m2() -> None:
    """M2: 4 个 A2A 工具改为 restricted (LLM 可见, 但需 mesh_action_broker 注入)."""
    perm = ToolPermission()
    for name in ("notify_agent", "handoff_conversation", "list_available_agents", "memory_query_agent"):
        assert perm.check(name) == "restricted", name
    # 既有 ask_agent 仍为 allow, 未受影响
    assert perm.check("ask_agent") == "allow"


# ── approach b: 既有契约字段未被改动 ─────────────────────────────


def test_existing_routing_decision_contract_unchanged() -> None:
    names = [f.name for f in dataclasses.fields(RoutingDecision)]
    assert names == ["agent_id", "matched_by", "content"]


def test_existing_interagent_link_contract_unchanged() -> None:
    names = [f.name for f in dataclasses.fields(InterAgentLink)]
    assert names == ["from_agent", "to_agent", "direction", "enabled"]
