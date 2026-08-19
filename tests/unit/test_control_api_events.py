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
    max_connections: int | None = None,
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
    kwargs: dict[str, Any] = {}
    if max_connections is not None:
        kwargs["max_connections"] = max_connections
    app.include_router(
        routes_events.build_router(
            event_bus or EventBus(), auth_dependency=auth_dep, tokens=parsed_tokens, **kwargs,
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


class TestConnectionLimit:
    """Fix-14: _EventStreamState 之前无限制接受 SSE 连接; 单个恶意或失控客户端
    可以开无限多个长连接耗尽服务端连接/内存资源 (无认领的 DoS 面)。"""

    def test_acquire_connection_succeeds_under_limit(self) -> None:
        state = routes_events._EventStreamState(max_connections=2)
        assert state.acquire_connection() is True
        assert state.acquire_connection() is True

    def test_acquire_connection_fails_at_limit(self) -> None:
        state = routes_events._EventStreamState(max_connections=2)
        state.acquire_connection()
        state.acquire_connection()
        assert state.acquire_connection() is False

    def test_release_connection_frees_a_slot(self) -> None:
        state = routes_events._EventStreamState(max_connections=1)
        assert state.acquire_connection() is True
        assert state.acquire_connection() is False
        state.release_connection()
        assert state.acquire_connection() is True

    def test_stream_rejected_with_429_when_at_capacity(self) -> None:
        """走真实 HTTP 路径: max_connections=0 (容量已耗尽的等价状态) 时, 新连接
        必须被直接拒绝 (429), 而不是被无限制接受。

        (不用两个嵌套的 client.stream() 模拟"已有一个连接占用名额": httpx
        TestClient 的 BlockingPortal 是单线程模型, 嵌套长连接请求会互相阻塞
        导致测试挂起, 与 acquire_connection() 本身的行为无关; max_connections=0
        直接命中同一段 "已达上限 → 429" 代码路径, 更快也更确定。)"""
        app = _make_app(max_connections=0)
        client = TestClient(app)
        with client.stream(
            "GET",
            "/api/v1/events/stream?heartbeat_seconds=5",
            headers={"Authorization": "Bearer test-token"},
        ) as resp:
            assert resp.status_code == 429

    def test_slot_freed_after_stream_completes_allows_new_connection(self) -> None:
        """一个连接正常结束 (这里用 max_chunks 模拟客户端读完/断开) 后释放的名额
        可以被新连接复用, 不会永久占用。"""
        app = _make_app(max_connections=1)
        client = TestClient(app)
        with client.stream(
            "GET",
            "/api/v1/events/stream?heartbeat_seconds=0.05&max_chunks=1",
            headers={"Authorization": "Bearer test-token"},
        ) as first:
            assert first.status_code == 200
            list(first.iter_text())  # 耗尽 generator, 触发 finally 释放连接名额

        with client.stream(
            "GET",
            "/api/v1/events/stream?heartbeat_seconds=5&max_chunks=1",
            headers={"Authorization": "Bearer test-token"},
        ) as second:
            assert second.status_code == 200


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

    def test_unregistered_non_public_event_type_is_fail_closed(self) -> None:
        """2026-08-19 fail-closed 回归: 未在 _EVENT_TYPE_SCOPES 登记、也不在
        _PUBLIC_EVENT_TYPES 白名单的事件类型, 窄 scope token 不可见 (仅 "*")。

        此前"已识别但未登记"一律直接放行 (fail-open) —— 新增敏感事件忘登记 scope
        会静默广播。现与 model.usage_recorded (usage:read 可见) 同批发射, 窄 token
        只应看到后者。"""
        event_bus = EventBus()
        app = _make_app(event_bus, tokens=[{"token": "usage-only", "scopes": ["usage:read"]}])
        self._fire(event_bus, "custom.unregistered_event", 7)  # 未登记且非公开 → 应被过滤
        self._fire(event_bus, "model.usage_recorded", 8)  # usage:read 可见

        client = TestClient(app)
        with client.stream(
            "GET",
            "/api/v1/events/stream?heartbeat_seconds=5&max_chunks=1",
            headers={"Authorization": "Bearer usage-only"},
        ) as resp:
            assert resp.status_code == 200
            chunks = list(resp.iter_text())
            assert len(chunks) == 1
            assert '"n": 8' in chunks[0]
            assert '"n": 7' not in chunks[0]

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

    def test_dict_payload_without_event_type_field_denied_for_scoped_caller(self) -> None:
        """Fix-22 回归: ON_START 的真实 payload 形态是 {"config": {...含密钥...}},
        没有 event_type 字段, append() 只能归为 "unknown"。之前 "unknown" 被
        当作"无需 scope 收窄"直接放行, usage:read-only 的调用方能拿到全部密钥。
        现在必须被拒绝, 只有 "*" scope 才能看到。"""
        import asyncio

        from isac.core.events import EventType

        event_bus = EventBus()
        app = _make_app(event_bus, tokens=[{"token": "usage-only", "scopes": ["usage:read"]}])
        asyncio.run(
            event_bus.fire_async(EventType.ON_START, {"config": {"control": {"api_token": "SUPER-SECRET"}}})
        )

        client = TestClient(app)
        with client.stream(
            "GET",
            "/api/v1/events/stream?heartbeat_seconds=0.05&max_chunks=1",
            headers={"Authorization": "Bearer usage-only"},
        ) as resp:
            assert resp.status_code == 200
            chunks = list(resp.iter_text())
            assert "SUPER-SECRET" not in chunks[0]

    def test_non_dict_payload_denied_for_scoped_caller(self) -> None:
        """Fix-22 回归: POST_MESSAGE 的真实 payload 形态是完整 ISACMessage 对象
        (非 dict), append() 的 isinstance(payload, dict) 检查直接失败归为
        "unknown"。之前会被当作"无需 scope 收窄"直接广播用户聊天原文。"""
        import asyncio
        from dataclasses import dataclass

        from isac.core.events import EventType

        @dataclass
        class _FakeMessage:
            content: str

        event_bus = EventBus()
        app = _make_app(event_bus, tokens=[{"token": "usage-only", "scopes": ["usage:read"]}])
        asyncio.run(event_bus.fire_async(EventType.POST_MESSAGE, _FakeMessage(content="my private secret")))

        client = TestClient(app)
        with client.stream(
            "GET",
            "/api/v1/events/stream?heartbeat_seconds=0.05&max_chunks=1",
            headers={"Authorization": "Bearer usage-only"},
        ) as resp:
            assert resp.status_code == 200
            chunks = list(resp.iter_text())
            assert "my private secret" not in chunks[0]

    def test_unknown_event_type_still_visible_to_wildcard_scope(self) -> None:
        """"*" scope (真正的全权限管理员 Token) 不受 Fix-22 影响, 仍能看到未分类
        的原始事件 (用于调试/观测), 只有窄 scope 的调用方才被拒绝。"""
        import asyncio

        from isac.core.events import EventType

        event_bus = EventBus()
        app = _make_app(event_bus, tokens=[{"token": "admin", "scopes": ["*"]}])
        asyncio.run(event_bus.fire_async(EventType.ON_START, {"config": {"marker": "ADMIN-CAN-SEE-THIS"}}))

        client = TestClient(app)
        with client.stream(
            "GET",
            "/api/v1/events/stream?heartbeat_seconds=0.05&max_chunks=1",
            headers={"Authorization": "Bearer admin"},
        ) as resp:
            assert resp.status_code == 200
            chunks = list(resp.iter_text())
            assert "ADMIN-CAN-SEE-THIS" in chunks[0]

    def test_session_cookie_caller_resolves_scopes(self) -> None:
        """Fix-45: 浏览器 EventSource 无法发自定义 Header, WebUI 只靠会话 Cookie
        认证 —— 此前 _resolve_caller_scopes 只看 Authorization 头, Cookie 客户端
        拿到空 scope 集 → 全部事件被过滤, SSE 功能性失效。现按 Cookie 解出 token
        再匹配 scope, 通配 Cookie 客户端应能看到事件。"""
        from isac.control.auth import (
            SESSION_COOKIE_NAME,
            generate_session_secret,
            make_token_only_dependency,
            parse_token_scopes,
            sign_session_cookie,
        )

        event_bus = EventBus()
        secret = generate_session_secret()
        parsed = parse_token_scopes({"tokens": [{"token": "admin", "scopes": ["*"]}]})

        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(
            routes_events.build_router(
                event_bus,
                auth_dependency=make_token_only_dependency(parsed, secret),
                tokens=parsed,
                session_secret=secret,
            ),
            prefix="/api/v1",
        )
        # 事件必须在 build_router 订阅之后发 (否则不进 state.buffer)
        self._fire(event_bus, "model.usage_recorded", 7)
        cookie_value = sign_session_cookie("admin", secret)
        client = TestClient(app)
        with client.stream(
            "GET",
            "/api/v1/events/stream?heartbeat_seconds=5&max_chunks=1",
            cookies={SESSION_COOKIE_NAME: cookie_value},
        ) as resp:
            assert resp.status_code == 200
            joined = "".join(resp.iter_text())
            assert '"n": 7' in joined  # Cookie 客户端收到其 scope 允许的事件

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
