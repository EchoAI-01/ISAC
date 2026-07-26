"""M1 observer/candidate 路由业务测试。

覆盖:
- MeshRouter.to_mesh_decision 填充 observer_agent_ids / candidate_agent_ids
- arbitrate 多候选按 gating_score 仲裁 (取最高)
- arbitrate 无候选返回 primary
- observer 不参与仲裁 (只观察)
- enabled=False 主链路零行为变化 (单主路由)
"""

from __future__ import annotations

from types import SimpleNamespace

from isac.runtime.mesh.models import MeshRoutingDecision
from isac.runtime.mesh.router import MeshRouter


def _routing_decision(agent_id: str | None = "a1", matched_by: str = "default") -> SimpleNamespace:
    return SimpleNamespace(agent_id=agent_id, matched_by=matched_by, content="hi")


def _agent_roles() -> dict[str, str]:
    """agent_id → mesh_role 字典 (模拟 AgentConfig.mesh_role)."""
    return {
        "a1": "primary",
        "a2": "observer",
        "a3": "candidate",
        "a4": "candidate",
    }


def test_to_mesh_decision_fills_observers_and_candidates() -> None:
    """to_mesh_decision 按角色配置填充 observer/candidate."""
    router = MeshRouter(agent_roles=_agent_roles())
    decision = router.to_mesh_decision(_routing_decision("a1"))
    assert decision.primary_agent_id == "a1"
    assert decision.observer_agent_ids == ["a2"]
    assert decision.candidate_agent_ids == ["a3", "a4"]


def test_to_mesh_decision_no_roles_returns_empty_observer_candidate() -> None:
    """无角色配置时 observer/candidate 为空 (退化为单主路由)."""
    router = MeshRouter()
    decision = router.to_mesh_decision(_routing_decision("a1"))
    assert decision.primary_agent_id == "a1"
    assert decision.observer_agent_ids == []
    assert decision.candidate_agent_ids == []


def test_arbitrate_returns_primary_when_no_candidates() -> None:
    """无候选时返回 primary (单主路由)."""
    router = MeshRouter()
    decision = MeshRoutingDecision(
        primary_agent_id="a1", matched_by="default", content="hi",
    )
    assert router.arbitrate(decision) == "a1"


def test_arbitrate_picks_highest_gating_score() -> None:
    """多候选按 gating_score 降序取最高者."""
    router = MeshRouter()
    decision = MeshRoutingDecision(
        primary_agent_id="a1", matched_by="default", content="hi",
        candidate_agent_ids=["a3", "a4"],
    )
    # gating_scores: a3=0.5, a4=0.9 → 选 a4
    scores = {"a3": 0.5, "a4": 0.9}
    winner = router.arbitrate(decision, gating_scores=scores)
    assert winner == "a4"


def test_arbitrate_falls_back_to_primary_when_scores_equal_or_missing() -> None:
    """候选分数缺失时返回 primary (保守, 不选未知分数候选)."""
    router = MeshRouter()
    decision = MeshRoutingDecision(
        primary_agent_id="a1", matched_by="default", content="hi",
        candidate_agent_ids=["a3", "a4"],
    )
    # 无 gating_scores 提供时返回 primary
    assert router.arbitrate(decision) == "a1"
    # 候选分数都 < primary 时返回 primary
    scores = {"a3": 0.1, "a4": 0.2}
    assert router.arbitrate(decision, gating_scores=scores) == "a1"


def test_arbitrate_observers_excluded() -> None:
    """observer 不参与仲裁 (只观察不回复)."""
    router = MeshRouter(agent_roles=_agent_roles())
    decision = MeshRoutingDecision(
        primary_agent_id="a1", matched_by="default", content="hi",
        observer_agent_ids=["a2"],
        candidate_agent_ids=["a3"],
    )
    # a2 是 observer 即使分数最高也不应被选; 候选 a3 分数低于 SWITCH_MARGIN 不切换
    scores = {"a2": 0.99, "a3": 0.1}  # a2 不在 candidates, a3 分数低
    winner = router.arbitrate(decision, gating_scores=scores)
    assert winner == "a1"  # observer a2 被排除; a3 不显著高于 primary; 返回 primary


def test_mesh_decision_reason_records_arbitration() -> None:
    """arbitrate 在 decision.reason 里记录仲裁结果 (可解释/可审计)."""
    router = MeshRouter()
    decision = MeshRoutingDecision(
        primary_agent_id="a1", matched_by="default", content="hi",
        candidate_agent_ids=["a3", "a4"],
    )
    scores = {"a3": 0.5, "a4": 0.9}
    winner = router.arbitrate(decision, gating_scores=scores)
    # reason 字段含仲裁说明 (供审计)
    assert winner == "a4"
    assert decision.reason  # 非空


# ── 默认零行为变化 ───────────────────────────────────────────────


def test_to_mesh_decision_preserves_base_routing_fields() -> None:
    """to_mesh_decision 不改 base 的 primary/matched_by/content (向后兼容)."""
    router = MeshRouter(agent_roles=_agent_roles())
    base = _routing_decision("a1", matched_by="trigger_word")
    base.content = "你好"
    decision = router.to_mesh_decision(base)
    assert decision.primary_agent_id == "a1"
    assert decision.matched_by == "trigger_word"
    assert decision.content == "你好"
