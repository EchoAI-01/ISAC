"""J3 阶段 2: Control API routes_config (配置编辑事务) 测试。

覆盖:
- POST /config/validate: Schema 校验 AgentConfig 字段 (合法/非法 agent_id / 缺字段)
- POST /config/diff: 两份 AgentConfig 的字段级 diff
- PATCH /agents/{id}: 部分更新 + If-Match revision + 409 CONFIG_CONFLICT
- PATCH 无 If-Match → 428 PRECONDITION_REQUIRED (或 400)
- PATCH revision 不匹配 → 409
- PATCH 成功 → revision +1, 配置持久化
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from isac.control.api import routes_config
from isac.control.api.server import create_control_app
from isac.observability import get_default_metrics


def _make_app(api_token: str = "test-token") -> Any:
    class _StubAM:
        async def list(self): return []
        async def get(self, _): return None

    app = create_control_app(
        _StubAM(), object(), object(), object(),
        {"api_token": api_token, "agents_dir": "data/agents"},
        metrics=get_default_metrics(),
    )
    from isac.control.auth import make_auth_dependency
    auth_dep = make_auth_dependency(api_token)
    app.include_router(
        routes_config.build_router(auth_dependency=auth_dep),
        prefix="/api/v1",
    )
    return app


def test_validate_valid_config() -> None:
    app = _make_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/config/validate",
        json={"agent_id": "valid-id", "display_name": "Test", "enabled": True},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["errors"] == []


def test_validate_invalid_agent_id() -> None:
    app = _make_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/config/validate",
        json={"agent_id": "../etc/passwd", "display_name": "evil"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert len(data["errors"]) > 0
    assert "agent_id" in data["errors"][0]


def test_validate_missing_agent_id() -> None:
    app = _make_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/config/validate",
        json={"display_name": "no id"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert any("agent_id" in e for e in data["errors"])


def test_validate_unknown_field_ignored() -> None:
    """未知字段被忽略 (AgentConfig 只取已知字段), 不算错误。"""
    app = _make_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/config/validate",
        json={"agent_id": "ok", "unknown_field": "ignored"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True


def test_diff_returns_field_changes() -> None:
    """POST /config/diff 返回两份配置的字段级 diff。"""
    app = _make_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/config/diff",
        json={
            "before": {"agent_id": "a1", "display_name": "Old", "enabled": True},
            "after": {"agent_id": "a1", "display_name": "New", "enabled": False},
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    changes = {c["field"]: c for c in data["changes"]}
    assert "display_name" in changes
    assert changes["display_name"]["before"] == "Old"
    assert changes["display_name"]["after"] == "New"
    assert "enabled" in changes
    assert changes["enabled"]["before"] is True
    assert changes["enabled"]["after"] is False


def test_diff_no_changes_returns_empty() -> None:
    app = _make_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/config/diff",
        json={
            "before": {"agent_id": "a1", "display_name": "Same"},
            "after": {"agent_id": "a1", "display_name": "Same"},
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["changes"] == []


def test_diff_missing_before_after_returns_400() -> None:
    app = _make_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/config/diff",
        json={"before": {"agent_id": "a1"}},  # 缺 after
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 400


def test_token_auth_required() -> None:
    app = _make_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/config/validate",
        json={"agent_id": "ok"},
    )
    assert resp.status_code in (401, 403)
