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
    tokens: list[dict] | None = None,
) -> Any:
    class _StubAM:
        async def list(self): return []
        async def get(self, _): return None

    app = create_control_app(
        _StubAM(), object(), object(), object(),
        {"api_token": api_token, "agents_dir": "data/agents"},
        metrics=get_default_metrics(),
    )
    from isac.control.auth import make_auth_dependency, make_token_only_dependency, parse_token_scopes

    parsed_tokens = parse_token_scopes({"tokens": tokens}) if tokens else None
    auth_dep = make_token_only_dependency(parsed_tokens) if parsed_tokens else make_auth_dependency(api_token)
    app.include_router(
        routes_events.build_router(
            event_bus or EventBus(), auth_dependency=auth_dep, tokens=parsed_tokens,
        ),
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


class TestScopeFiltering:
    """Fix-13: CONTROL_PLANE_SPEC.md §8.3 "实时通道只发送当前 Token scope 可读的
    资源" 在引入 Fix-12 的 Token Scope 模型之前完全没有实现 —— SSE 端点对所有
    EventType 无差别推送给任何已认证调用方。"""

    def _fire(self, event_bus: EventBus, event_type: str, n: int) -> None:
        import asyncio

        from isac.core.events import EventType

        asyncio.run(event_bus.fire_async(EventType.POST_MESSAGE, {"event_type": event_type, "n": n}))

    def test_scoped_caller_only_sees_events_matching_its_scope(self) -> None:
        """只有 usage:read scope 的调用方订阅事件流, 应该收到 model.usage_recorded
        (usage:read), 收不到 agent.status_changed (需要 agent:read)。"""
        event_bus = EventBus()
        app = _make_app(event_bus, tokens=[{"token": "usage-only", "scopes": ["usage:read"]}])
        self._fire(event_bus, "agent.status_changed", 1)
        self._fire(event_bus, "model.usage_recorded", 2)

        client = TestClient(app)
        with client.stream(
            "GET",
            "/api/v1/events/stream?heartbeat_seconds=5&max_chunks=1",
            headers={"Authorization": "Bearer usage-only"},
        ) as resp:
            assert resp.status_code == 200
            chunks = list(resp.iter_text())
            assert len(chunks) == 1
            assert '"n": 2' in chunks[0]
            assert '"n": 1' not in chunks[0]

    def test_wildcard_scope_sees_every_event_type(self) -> None:
        """"*" scope 的调用方 (如管理员 Token) 不受任何事件类型的 scope 收窄。"""
        event_bus = EventBus()
        app = _make_app(event_bus, tokens=[{"token": "admin", "scopes": ["*"]}])
        self._fire(event_bus, "agent.status_changed", 1)
        self._fire(event_bus, "model.usage_recorded", 2)

        client = TestClient(app)
        with client.stream(
            "GET",
            "/api/v1/events/stream?heartbeat_seconds=5&max_chunks=2",
            headers={"Authorization": "Bearer admin"},
        ) as resp:
            assert resp.status_code == 200
            # SSE 多次 yield 可能被合并进同一个 HTTP chunk (StreamingResponse 不
            # 保证 1 yield = 1 chunk), 所以只断言内容都存在, 不假设 chunk 数量。
            joined = "".join(resp.iter_text())
            assert '"n": 1' in joined
            assert '"n": 2' in joined

    def test_event_type_without_defined_scope_is_not_filtered(self) -> None:
        """没有预定义 scope 要求的事件类型 (CONTROL_PLANE_SPEC.md §6.1 未列出对应
        资源的 scope, 如 channel.status_changed) 不因调用方 scope 收窄被过滤掉,
        不臆造 spec 未定义的 scope 名称。"""
        event_bus = EventBus()
        app = _make_app(event_bus, tokens=[{"token": "usage-only", "scopes": ["usage:read"]}])
        self._fire(event_bus, "channel.status_changed", 9)

        client = TestClient(app)
        with client.stream(
            "GET",
            "/api/v1/events/stream?heartbeat_seconds=5&max_chunks=1",
            headers={"Authorization": "Bearer usage-only"},
        ) as resp:
            assert resp.status_code == 200
            chunks = list(resp.iter_text())
            assert len(chunks) == 1
            assert '"n": 9' in chunks[0]

    def test_unconfigured_tokens_leaves_stream_unfiltered(self) -> None:
        """未配置 control.tokens[] (纯扁平 api_token) 时行为不变: 全部事件都可见,
        不引入任何过滤 (向后兼容)。"""
        event_bus = EventBus()
        app = _make_app(event_bus)
        self._fire(event_bus, "agent.status_changed", 1)

        client = TestClient(app)
        with client.stream(
            "GET",
            "/api/v1/events/stream?heartbeat_seconds=5&max_chunks=1",
            headers={"Authorization": "Bearer test-token"},
        ) as resp:
            assert resp.status_code == 200
            chunks = list(resp.iter_text())
            assert len(chunks) == 1
            assert '"n": 1' in chunks[0]

    def test_create_control_app_wires_tokens_into_events_route(self) -> None:
        """回归防护: Fix-12 曾出现 server.py 解析出 scope 模型却没有真正传给
        路由 (auth_dependency 仍用扁平 api_token) 的接线遗漏; 这里直接走
        create_control_app(event_bus=...) 的生产路径 (不像上面 _make_app 那样
        手动 include_router 绕过 server.py 的挂载逻辑), 断言 scope 过滤在真实
        生产接线下也生效。"""
        from isac.control.api.server import create_control_app

        class _StubAM:
            async def list(self): return []
            async def get(self, _): return None

        event_bus = EventBus()
        app = create_control_app(
            _StubAM(), object(), object(), object(),
            {
                "api_token": "fallback-admin-token",
                "tokens": [{"token": "usage-only", "scopes": ["usage:read"]}],
                "agents_dir": "data/agents",
            },
            metrics=get_default_metrics(),
            event_bus=event_bus,
        )
        self._fire(event_bus, "agent.status_changed", 1)
        self._fire(event_bus, "model.usage_recorded", 2)

        client = TestClient(app)
        with client.stream(
            "GET",
            "/api/v1/events/stream?heartbeat_seconds=5&max_chunks=1",
            headers={"Authorization": "Bearer usage-only"},
        ) as resp:
            assert resp.status_code == 200
            chunks = list(resp.iter_text())
            assert len(chunks) == 1
            assert '"n": 2' in chunks[0]
            assert '"n": 1' not in chunks[0]
