"""J2 阶段 3: ModelRouter 打分排序单元测试。

覆盖:
- cost_ceiling 过滤 (排除 cost_tier 高于上限的候选)
- latency_target 过滤 (排除 latency_tier 慢于目标的候选)
- health 过滤 (record_health 标记不健康后, 该 provider 不在候选)
- 多候选选最高分 (cost=low + latency=fast 胜过 cost=standard + latency=standard)
- 返回 reason 含各因子 (operation/cost/latency/health/preference)
- 偏好加权 (preferred provider 在同分时胜出)
- 无候选返回 None
"""

from __future__ import annotations

from isac.provider.catalog import ModelCatalog, ModelDescriptor
from isac.provider.router import ModelRouter


def _descriptor(
    *,
    provider_id: str,
    model_id: str = "m1",
    operations: set[str] | None = None,
    modalities_in: set[str] | None = None,
    modalities_out: set[str] | None = None,
    cost_tier: str = "standard",
    latency_tier: str = "standard",
) -> ModelDescriptor:
    return ModelDescriptor(
        provider_id=provider_id,
        model_id=model_id,
        operations=operations or {"image_gen"},
        modalities_in=modalities_in or {"text"},
        modalities_out=modalities_out or {"image"},
        cost_tier=cost_tier,
        latency_tier=latency_tier,
    )


def _catalog(*descriptors: ModelDescriptor) -> ModelCatalog:
    cat = ModelCatalog()
    for d in descriptors:
        cat.register(d)
    return cat


def test_cost_ceiling_excludes_high_tier() -> None:
    cat = _catalog(
        _descriptor(provider_id="cheap", cost_tier="low"),
        _descriptor(provider_id="expensive", cost_tier="high"),
    )
    router = ModelRouter(cat)
    sel = router.select(operation="image_gen", cost_ceiling="low")
    assert sel is not None
    assert sel.descriptor.provider_id == "cheap"


def test_latency_target_excludes_slow() -> None:
    cat = _catalog(
        _descriptor(provider_id="fast", latency_tier="fast"),
        _descriptor(provider_id="slow", latency_tier="slow"),
    )
    router = ModelRouter(cat)
    sel = router.select(operation="image_gen", latency_target="fast")
    assert sel is not None
    assert sel.descriptor.provider_id == "fast"


def test_record_health_excludes_unhealthy() -> None:
    cat = _catalog(
        _descriptor(provider_id="p1"),
        _descriptor(provider_id="p2"),
    )
    router = ModelRouter(cat)
    router.record_health("p1", healthy=False)
    sel = router.select(operation="image_gen")
    assert sel is not None
    assert sel.descriptor.provider_id == "p2"


def test_record_health_restores_when_healthy_again() -> None:
    cat = _catalog(_descriptor(provider_id="p1"))
    router = ModelRouter(cat)
    router.record_health("p1", healthy=False)
    assert router.select(operation="image_gen") is None
    router.record_health("p1", healthy=True)
    sel = router.select(operation="image_gen")
    assert sel is not None
    assert sel.descriptor.provider_id == "p1"


def test_highest_score_wins_among_multiple_candidates() -> None:
    # 两个候选: p1 = low cost + fast latency (高分); p2 = standard cost + standard latency (中分)
    cat = _catalog(
        _descriptor(provider_id="p1", cost_tier="low", latency_tier="fast"),
        _descriptor(provider_id="p2", cost_tier="standard", latency_tier="standard"),
    )
    router = ModelRouter(cat)
    sel = router.select(operation="image_gen")
    assert sel is not None
    assert sel.descriptor.provider_id == "p1"


def test_reason_contains_factors() -> None:
    cat = _catalog(_descriptor(provider_id="p1", cost_tier="low", latency_tier="fast"))
    router = ModelRouter(cat)
    sel = router.select(
        operation="image_gen", cost_ceiling="low", latency_target="fast"
    )
    assert sel is not None
    reason = sel.reason
    assert "operation" in reason
    assert "score" in reason
    assert "cost_tier" in reason or "cost" in reason.lower()
    assert "latency" in reason.lower()
    assert "healthy" in reason.lower() or "health" in reason.lower()


def test_user_preference_ties_breaker() -> None:
    # 两个 cost/latency 相同的候选; preferred provider 应胜出
    cat = _catalog(
        _descriptor(provider_id="p1", cost_tier="low", latency_tier="fast"),
        _descriptor(provider_id="p2", cost_tier="low", latency_tier="fast"),
    )
    router = ModelRouter(cat)
    router.set_preference("p2")
    sel = router.select(operation="image_gen")
    assert sel is not None
    assert sel.descriptor.provider_id == "p2"


def test_no_candidates_returns_none() -> None:
    cat = _catalog()
    router = ModelRouter(cat)
    assert router.select(operation="image_gen") is None


def test_authorization_filter_excludes_unauthorized_operation() -> None:
    cat = _catalog(_descriptor(provider_id="p1", operations={"image_gen"}))
    router = ModelRouter(cat)
    # allowed_operations 不含 image_gen → 直接 None
    sel = router.select(
        operation="image_gen", allowed_operations={"stt"}
    )
    assert sel is None


def test_modality_filter_excludes_non_matching() -> None:
    cat = _catalog(
        _descriptor(
            provider_id="p1",
            modalities_in={"text"},
            modalities_out={"image"},
        ),
        _descriptor(
            provider_id="p2",
            modalities_in={"audio"},
            modalities_out={"text"},
        ),
    )
    router = ModelRouter(cat)
    # 要求 modalities_in={text}, 只有 p1 匹配
    sel = router.select(operation="image_gen", modalities_in={"text"})
    assert sel is not None
    assert sel.descriptor.provider_id == "p1"
