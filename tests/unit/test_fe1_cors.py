"""FE1: 前后端分离基建自检 (CORS / Session Cookie SameSite / WebUI deprecated)。

DEVELOPMENT_PLAN.md §四 FE1 验收:
- CORS 策略落地 (origins 白名单可配, 默认不放开)。
- 跨源认证 (分离 origin 时 SameSite=Lax, 同源 Strict; Bearer Token 双轨保留)。
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


def _make_control_app(config_extra: dict[str, Any] | None = None) -> Any:
    """构造挂载全部路由的 control app (与 scripts/export_openapi.py 同 mock 注入)。"""
    from isac.control.api.server import create_control_app

    mock = MagicMock()
    config: dict[str, Any] = {
        "api_token": "test-token",
        "agents_dir": "data/agents",
        "routing_rules_path": "data/routing.jsonc",
        "links_path": "data/links.jsonc",
    }
    if config_extra:
        config.update(config_extra)
    return create_control_app(
        agent_manager=mock,
        router=mock,
        bus=mock,
        plugin_manager=mock,
        config=config,
        metrics=mock,
        usage_store=mock,
        subagent_supervisor=mock,
        provider_manager=mock,
        model_catalog=mock,
        artifact_store=mock,
        session_manager=mock,
        metadata_store=mock,
        event_bus=mock,
        sparse_resolver=mock,
        workflow_engine=mock,
        identity_resolver=mock,
        vector_resolver=mock,
        channel_registry=mock,
    )


def _make_auth_app(samesite: str) -> Any:
    """单独构造只含 /auth/session 的 app (不经 CSRF middleware, 直接测 samesite)。"""
    from fastapi import FastAPI

    from isac.control.api.routes_auth import build_router

    app = FastAPI()
    secret = b"x" * 32  # sign_session_cookie 用 HMAC, 任意定长 bytes 即可
    app.include_router(
        build_router("test-token", None, secret, samesite=samesite), prefix="/api/v1"
    )
    return app


def test_cors_disabled_by_default() -> None:
    """默认无 cors 配置 → 不加 CORSMiddleware (跨源预检不返回 ACAO 头)。"""
    from fastapi.testclient import TestClient

    client = TestClient(_make_control_app())
    resp = client.options(
        "/health",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in resp.headers, "默认应不放开 CORS"


def test_cors_enabled_for_configured_origins() -> None:
    """cors.origins 配置 → 预检返回 ACAO 允许该 origin。"""
    from fastapi.testclient import TestClient

    app = _make_control_app({"cors": {"origins": ["http://localhost:5173"]}})
    client = TestClient(app)
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200, "预检应被 CORSMiddleware 直接放行"
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_unlisted_origin() -> None:
    """cors.origins 不含的 origin → 不回 ACAO (不放开)。"""
    from fastapi.testclient import TestClient

    app = _make_control_app({"cors": {"origins": ["http://localhost:5173"]}})
    client = TestClient(app)
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") != "http://evil.example"


def test_session_samesite_strict_default() -> None:
    """同源 (无 cors) → 会话 Cookie SameSite=Strict。"""
    from fastapi.testclient import TestClient

    client = TestClient(_make_auth_app("strict"))
    resp = client.post("/api/v1/auth/session", json={"token": "test-token"})
    assert resp.status_code == 200
    assert "samesite=strict" in resp.headers.get("set-cookie", "").lower()


def test_session_samesite_lax_when_cors_origins() -> None:
    """分离 origin (cors.origins 非空) → 会话 Cookie SameSite=Lax (跨源可带)。"""
    from fastapi.testclient import TestClient

    client = TestClient(_make_auth_app("lax"))
    resp = client.post("/api/v1/auth/session", json={"token": "test-token"})
    assert resp.status_code == 200
    assert "samesite=lax" in resp.headers.get("set-cookie", "").lower()
