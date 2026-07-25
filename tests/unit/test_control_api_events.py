"""J3 阶段 4: Control API routes_events SSE 测试 (简化)。

覆盖:
- GET /events/stream 返回 text/event-stream content-type
- 至少能收到一个 chunk (心跳或事件)
- Last-Event-ID header 不报错
- Bearer Token 认证
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from isac.control.api import routes_events
from isac.control.api.server import create_control_app
from isac.gateway.event_bus import EventBus
from isac.observability import get_default_metrics


def _make_app(
    event_bus: EventBus | None = None,
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
        routes_events.build_router(event_bus or EventBus(), auth_dependency=auth_dep),
        prefix="/api/v1",
    )
    return app


def test_events_stream_returns_sse_content_type() -> None:
    """GET /events/stream 返回 text/event-stream; 读 1 个心跳 chunk (max_chunks=1)。"""
    app = _make_app()
    client = TestClient(app)
    with client.stream(
        "GET",
        "/api/v1/events/stream?heartbeat_seconds=0.05&max_chunks=1",
        headers={"Authorization": "Bearer test-token"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        chunks = list(resp.iter_text())
        assert len(chunks) >= 1
        # 第一个 chunk 应是心跳 (": heartbeat ...")
        assert "heartbeat" in chunks[0] or "data:" in chunks[0]


def test_events_stream_with_last_event_id_header() -> None:
    """Last-Event-ID header 不报错; max_chunks=1 自动退出。"""
    app = _make_app()
    client = TestClient(app)
    with client.stream(
        "GET",
        "/api/v1/events/stream?heartbeat_seconds=0.05&max_chunks=1",
        headers={"Authorization": "Bearer test-token", "Last-Event-ID": "5"},
    ) as resp:
        assert resp.status_code == 200
        chunks = list(resp.iter_text())
        assert len(chunks) >= 1


def test_events_stream_last_event_id_header_actually_skips_seen_events() -> None:
    """Fix-11: last_event_id 之前只绑定 query 参数, 真实 EventSource 重连时发的
    Last-Event-ID 请求头会被忽略, 导致断线恢复重复推送已经收到过的事件。这里
    预先写入 3 条事件, 用 Header (不是 query) 声明"已看到 id=2", 断言只收到
    id=3 之后的事件, 而不是把 3 条全部重推一遍。"""
    import asyncio

    from isac.core.events import EventType

    event_bus = EventBus()
    app = _make_app(event_bus)

    async def _fire_three() -> None:
        for i in range(3):
            await event_bus.fire_async(EventType.POST_MESSAGE, {"event_type": "agent.status_changed", "n": i})

    asyncio.run(_fire_three())

    client = TestClient(app)
    with client.stream(
        "GET",
        "/api/v1/events/stream?heartbeat_seconds=5&max_chunks=1",
        headers={"Authorization": "Bearer test-token", "Last-Event-ID": "2"},
    ) as resp:
        assert resp.status_code == 200
        chunks = list(resp.iter_text())
        assert len(chunks) == 1
        assert '"n": 2' in chunks[0]
        assert '"n": 0' not in chunks[0]
        assert '"n": 1' not in chunks[0]


def test_token_auth_required() -> None:
    app = _make_app()
    client = TestClient(app)
    with client.stream("GET", "/api/v1/events/stream") as resp:
        assert resp.status_code in (401, 403)
