"""S4 身份归一控制面路由单测。

验证 routes_identity.build_router: identity_resolver=None 时返回 None (不挂载);
注入 resolver 时 bind / list conflicts / resolve conflict 三个 REST 入口按
IdentityResolver 真实 API 工作 (resolve_conflict 不存在 conflict_id → 404;
bind 真实调用 resolver.bind 并回传 bound=True)。无 auth/scope 依赖时路由开放
(与其他控制面路由的无认证回归一致)。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from isac.control.api import routes_identity
from isac.gateway.identity.resolver import IdentityResolver


@pytest.fixture
def resolver() -> IdentityResolver:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    r = IdentityResolver(db_path=tmp.name)  # 无 user_mapper, 仅测 person_identities 表
    yield r
    Path(tmp.name).unlink(missing_ok=True)


def _client(resolver: IdentityResolver) -> TestClient:
    app = FastAPI()
    router = routes_identity.build_router(resolver)
    assert router is not None
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_build_router_none_resolver_returns_none() -> None:
    assert routes_identity.build_router(None) is None


def test_bind_identity_writes_verified_row(resolver: IdentityResolver) -> None:
    """POST /identity/bind → resolver.bind 落 person_identities verified=1。"""
    client = _client(resolver)
    resp = client.post("/api/v1/identity/bind", json={
        "person_id": "p1", "platform": "qq", "platform_user_id": "qq-1",
        "display_name": "小明",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"person_id": "p1", "platform": "qq", "bound": True}
    # resolver 已落 verified 记录, resolve 命中
    person_id = asyncio.run(resolver.resolve("qq", "qq-1", "小明"))
    assert person_id == "p1"


def test_list_conflicts_returns_empty_initially(resolver: IdentityResolver) -> None:
    """GET /identity/conflicts → 初始无冲突时返回空列表。"""
    client = _client(resolver)
    resp = client.get("/api/v1/identity/conflicts")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_conflicts_returns_pending_after_arbitration(resolver: IdentityResolver) -> None:
    """arbitrate_conflict 写入低置信度冲突 → list_conflicts 能读到。"""
    from isac.gateway.identity.models import PersonIdentity

    # 直接用 resolver 写一条低置信度冲突 (<0.7)
    candidates = [
        PersonIdentity(person_id="p_a", aliases=["a"], confidence=0.3, verified=False),
        PersonIdentity(person_id="p_b", aliases=["b"], confidence=0.4, verified=False),
    ]
    winner = resolver.arbitrate_conflict(candidates)
    assert winner is not None  # 写入了 identity_conflicts
    client = _client(resolver)
    resp = client.get("/api/v1/identity/conflicts")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["resolved"] == 0


def test_resolve_conflict_marks_resolved(resolver: IdentityResolver) -> None:
    """POST /identity/conflicts/{id}/resolve → conflict 被标记 resolved + person_id 更新。"""
    from isac.gateway.identity.models import PersonIdentity

    candidates = [
        PersonIdentity(person_id="p_a", aliases=["a"], confidence=0.3, verified=False),
        PersonIdentity(person_id="p_b", aliases=["b"], confidence=0.4, verified=False),
    ]
    resolver.arbitrate_conflict(candidates)
    conflicts = resolver.list_conflicts()
    conflict_id = conflicts[0]["conflict_id"]
    # 人工裁决选择 p_b (与自动 winner 不同)
    client = _client(resolver)
    resp = client.post(
        f"/api/v1/identity/conflicts/{conflict_id}/resolve", json={"person_id": "p_b"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"conflict_id": conflict_id, "resolved": True, "person_id": "p_b"}
    # 再次 list_conflicts 不再出现 (resolved=1 被过滤)
    assert client.get("/api/v1/identity/conflicts").json() == []


def test_resolve_unknown_conflict_returns_404(resolver: IdentityResolver) -> None:
    """不存在的 conflict_id → 404。"""
    client = _client(resolver)
    resp = client.post(
        "/api/v1/identity/conflicts/nope-id/resolve", json={"person_id": "p_x"}
    )
    assert resp.status_code == 404


def test_resolve_unknown_conflict_audits_404(resolver: IdentityResolver) -> None:
    from isac.control.audit import AuditLog

    audit = AuditLog()
    app = FastAPI()
    router = routes_identity.build_router(resolver, audit_log=audit)
    assert router is not None
    app.include_router(router, prefix="/api/v1")

    response = TestClient(app).post(
        "/api/v1/identity/conflicts/nope-id/resolve", json={"person_id": "p_x"}
    )

    assert response.status_code == 404
    entries = audit.query(action="resolve_identity_conflict")
    assert len(entries) == 1
    assert entries[0]["status_code"] == 404


def test_resolve_conflict_method_directly(resolver: IdentityResolver) -> None:
    """直接调用 resolver.resolve_conflict: 存在 → True + resolved=1; 不存在 → False。"""
    from isac.gateway.identity.models import PersonIdentity

    candidates = [
        PersonIdentity(person_id="p_a", aliases=["a"], confidence=0.3, verified=False),
    ]
    resolver.arbitrate_conflict(candidates)
    conflicts = resolver.list_conflicts()
    conflict_id = conflicts[0]["conflict_id"]
    assert asyncio.run(resolver.resolve_conflict(conflict_id, "p_manual")) is True
    # 二次 resolve 不存在的 id → False
    assert asyncio.run(resolver.resolve_conflict("non-existent", "p_x")) is False


# 保留未使用 import 警告抑制
_ = pytest, Any
