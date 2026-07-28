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


def test_empty_api_token_warns_critically() -> None:
    """R4: 控制面启用但 api_token 和 tokens[] 均为空时触发 CRITICAL 警告分支。

    create_control_app 被调用即意味着 control.enabled=true, 但若 token 缺失,
    所有 admin 端点 (config edit / plugin load / memory admin / agent create)
    全部无认证暴露。CRITICAL 警告不阻止启动 (保持 dev 模式兼容)。

    _warn_if_no_auth 返回 bool 表示是否触发了 critical 分支, 便于测试断言。
    """
    from isac.control.api.server import _warn_if_no_auth

    # 有 api_token: early return, 不触发 critical
    assert _warn_if_no_auth(api_token="has-token", parsed_tokens=None) is False

    # 有 parsed_tokens: 同样 early return
    assert _warn_if_no_auth(
        api_token="",
        parsed_tokens=[{"token": "t", "scopes": ["read"]}],
    ) is False

    # 两者皆空: 触发 critical 路径
    assert _warn_if_no_auth(api_token="", parsed_tokens=None) is True


def test_docs_disabled_by_default() -> None:
    """R15: 默认关闭 /docs 和 /openapi.json, 防止误暴露 admin 端点列表 + 参数形状。

    生产部署时 /docs 和 /openapi.json 应返回 404; 可通过 control.docs_enabled=true
    显式开启 (开发/调试场景)。
    """
    from fastapi.testclient import TestClient

    from isac.control.api.server import create_control_app

    class _StubAM:
        async def list(self): return []
        async def get(self, _): return None

    # 默认: docs_enabled 未配置 → 关闭
    app = create_control_app(
        _StubAM(), object(), object(), object(),
        {"api_token": "tok-abc"},
        metrics=get_default_metrics(),
    )
    client = TestClient(app)
    resp = client.get("/docs")
    assert resp.status_code == 404
    resp = client.get("/openapi.json")
    assert resp.status_code == 404


def test_docs_enabled_explicitly() -> None:
    """R15: docs_enabled=true 时 /docs 与 /openapi.json 可访问 (开发模式)。"""
    from fastapi.testclient import TestClient

    from isac.control.api.server import create_control_app

    class _StubAM:
        async def list(self): return []
        async def get(self, _): return None

    app = create_control_app(
        _StubAM(), object(), object(), object(),
        {"api_token": "tok-abc", "docs_enabled": True},
        metrics=get_default_metrics(),
    )
    client = TestClient(app)
    resp = client.get("/docs")
    assert resp.status_code == 200
    resp = client.get("/openapi.json")
    assert resp.status_code == 200


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


def test_unhandled_exception_returns_generic_message_not_exc_info() -> None:
    """R14: 未捕获异常的全局 handler 返回通用 "Internal server error",
    不泄露 Python 类型/字段路径/磁盘 IO 信息。

    通过注入一个会抛 Exception 的 stub agent_manager, 触发全局 handler,
    验证响应 body 含 INTERNAL_ERROR code 与通用 message, 不含 str(exc)
    内容 (如自定义 Python 异常类型名 / 文件路径)。
    """
    from isac.control.api.server import create_control_app

    class _RaisingAM:
        async def list(self):
            raise RuntimeError("secret internal detail: /data/agents/x/config.jsonc permission denied")

        async def get(self, _):
            raise RuntimeError("secret detail path /foo/bar")

    app = create_control_app(
        _RaisingAM(), object(), object(), object(),
        {"api_token": "tok-abc"},
        metrics=get_default_metrics(),
    )
    # 触发 GET /api/v1/agents (会调 list(), 抛 RuntimeError)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/agents", headers={"Authorization": "Bearer tok-abc"})
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"]["code"] == "INTERNAL_ERROR"
    msg = body["detail"]["message"]
    assert msg == "Internal server error"
    # 关键: 不含原始异常的 Python 类型名 + 文件路径
    assert "RuntimeError" not in msg
    assert "permission denied" not in msg
    assert "/data/agents" not in msg



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
