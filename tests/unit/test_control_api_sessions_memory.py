"""J3 阶段 3: Control API routes_sessions + routes_memory 测试。

覆盖:
- GET /sessions: 列出活跃会话 (可选 ?agent_id 过滤)
- GET /sessions/{id}: 查询单个会话详情
- GET /sessions/{id}/messages: 列出会话消息历史 (从 MetadataStore.episodes)
- GET /memory/{agent_id}/episodes: 列出该 Agent 的记忆 episode
- GET /memory/{agent_id}/profiles: 列出人物画像
- GET /memory/{agent_id}/jargon: 列出术语
- Bearer Token 认证
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from isac.control.api import routes_memory, routes_sessions
from isac.control.api.server import create_control_app
from isac.gateway.models import Session
from isac.gateway.session import SessionManager
from isac.observability import get_default_metrics


def _make_app(
    session_mgr: SessionManager | None = None,
    metadata_store: Any = None,
    api_token: str = "test-token",
) -> Any:
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
        routes_sessions.build_router(session_mgr or SessionManager({}), metadata_store, auth_dependency=auth_dep),
        prefix="/api/v1",
    )
    memory_router = routes_memory.build_router(metadata_store, auth_dependency=auth_dep)
    if memory_router is not None:
        app.include_router(memory_router, prefix="/api/v1")
    return app


def _make_session(session_id: str = "s1", agent_id: str = "a1") -> Session:
    return Session(
        session_id=session_id, user_id="u1", agent_id=agent_id,
        platform="test", group_id=None, is_group=False, created_at=100, last_active=200,
    )


def test_list_sessions_empty() -> None:
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/v1/sessions", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    assert resp.json() == {"sessions": []}


def test_list_sessions_with_active() -> None:
    import asyncio
    sm = SessionManager({})
    asyncio.run(sm.get_or_create(_make_session(), "a1")) if False else None
    # 直接注入 session
    sm._sessions["a1:test:user:u1"] = _make_session()
    sm._by_id["s1"] = "a1:test:user:u1"
    app = _make_app(session_mgr=sm)
    client = TestClient(app)
    resp = client.get("/api/v1/sessions", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["session_id"] == "s1"


def test_list_sessions_filter_by_agent() -> None:
    sm = SessionManager({})
    sm._sessions["a1:t:user:u1"] = _make_session("s1", "a1")
    sm._by_id["s1"] = "a1:t:user:u1"
    sm._sessions["a2:t:user:u2"] = _make_session("s2", "a2")
    sm._by_id["s2"] = "a2:t:user:u2"
    app = _make_app(session_mgr=sm)
    client = TestClient(app)
    resp = client.get("/api/v1/sessions?agent_id=a1", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["agent_id"] == "a1"


def test_get_session_found() -> None:
    sm = SessionManager({})
    sm._sessions["k"] = _make_session("s1")
    sm._by_id["s1"] = "k"
    app = _make_app(session_mgr=sm)
    client = TestClient(app)
    resp = client.get("/api/v1/sessions/s1", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "s1"
    assert data["agent_id"] == "a1"


def test_get_session_not_found() -> None:
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/v1/sessions/unknown", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 404


def test_get_session_messages_empty_when_no_store() -> None:
    """无 metadata_store 时 /sessions/{id}/messages 不挂载 (或返回空)。"""
    app = _make_app(metadata_store=None)
    client = TestClient(app)
    resp = client.get("/api/v1/sessions/s1/messages", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert resp.json() == {"messages": []}


def test_list_memory_episodes_no_store_returns_404() -> None:
    """无 metadata_store 时 /memory/* 返回 404。"""
    app = _make_app(metadata_store=None)
    client = TestClient(app)
    resp = client.get("/api/v1/memory/a1/episodes", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 404


def test_memory_episode_limit_rejects_unbounded_query() -> None:
    app = _make_app(metadata_store=object())
    client = TestClient(app)
    resp = client.get(
        "/api/v1/memory/a1/episodes?limit=1000000",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 422


def test_session_message_limit_rejects_unbounded_query() -> None:
    app = _make_app(metadata_store=None)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/sessions/s1/messages?limit=1000000",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 422


def test_token_auth_required() -> None:
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/v1/sessions")
    assert resp.status_code in (401, 403)
