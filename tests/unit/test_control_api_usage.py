"""J1 Usage REST API 测试 (CONTROL_PLANE_SPEC.md 3.5): /usage/models/{summary,events,timeseries}。

认证沿用与其余控制面路由相同的扁平 Bearer Token; 计量关闭 (usage_store=None)
时路由不挂载, 404 而不是假装有数据。
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from isac.control.api.server import create_control_app
from isac.core.types import TokenUsage
from isac.observability.usage.models import ModelUsageEvent
from isac.observability.usage.storage import UsageStore
from isac.plugin.runtime.manager import PluginManager
from isac.router.router import MessageRouter
from isac.router.types import RoutingRules
from isac.runtime.bus import InterAgentBus
from isac.runtime.manager import AgentManager

API_TOKEN = "secret-token-123"
AUTH_HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}


class _StubProviderManager:
    def for_agent(self, config: Any) -> None:
        return None


def _build_app(usage_store: UsageStore | None, tmp_path) -> Any:
    """构造一个仅用于测试的 FastAPI app, agent/router/plugin 子系统用最小替身。"""
    services = {
        "global_config": {},
        "provider_manager": _StubProviderManager(),
        "memory_factory": lambda namespace: None,
    }
    agent_manager = AgentManager(services)
    bus = InterAgentBus()
    router = MessageRouter(RoutingRules(), agents_provider=agent_manager.routing_infos)
    plugin_manager = PluginManager({})
    return create_control_app(
        agent_manager=agent_manager,
        router=router,
        bus=bus,
        plugin_manager=plugin_manager,
        config={
            "api_token": API_TOKEN,
            "agents_dir": str(tmp_path / "agents"),
            "routing_rules_path": str(tmp_path / "routing.jsonc"),
            "links_path": str(tmp_path / "links.jsonc"),
            "audit_log_path": str(tmp_path / "audit.ndjson"),
        },
        usage_store=usage_store,
    )


_event_id_seq = itertools.count()


def _event(**kw: Any) -> ModelUsageEvent:
    base: dict[str, Any] = dict(
        event_id=f"e-{next(_event_id_seq)}",
        trace_id="",
        request_id="",
        agent_id="a1",
        session_id="s1",
        provider="P",
        model="m",
        modality="text",
        operation="chat",
        created_at=100,
    )
    base.update(kw)
    return ModelUsageEvent(**base)


@pytest.mark.asyncio
async def test_usage_router_not_mounted_when_usage_disabled(tmp_path) -> None:
    from fastapi.testclient import TestClient

    app = _build_app(None, tmp_path)
    client = TestClient(app)
    response = client.get("/api/v1/usage/models/summary", headers=AUTH_HEADERS)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_summary_endpoint_requires_auth(tmp_path) -> None:
    from fastapi.testclient import TestClient

    store = UsageStore(":memory:")
    await store.start()
    try:
        app = _build_app(store, tmp_path)
        client = TestClient(app)
        response = client.get("/api/v1/usage/models/summary")
        assert response.status_code == 401
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_summary_endpoint_returns_global_aggregate(tmp_path) -> None:
    from fastapi.testclient import TestClient

    store = UsageStore(":memory:")
    await store.start()
    try:
        await store.insert_many(
            [
                _event(usage=TokenUsage(prompt_tokens=10, completion_tokens=5)),
                _event(usage=TokenUsage(prompt_tokens=20, completion_tokens=15)),
            ]
        )
        app = _build_app(store, tmp_path)
        client = TestClient(app)
        response = client.get("/api/v1/usage/models/summary", headers=AUTH_HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["request_count"] == 2
        assert body[0]["total_tokens"] == 50
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_summary_endpoint_groups_by_agent_id(tmp_path) -> None:
    from fastapi.testclient import TestClient

    store = UsageStore(":memory:")
    await store.start()
    try:
        await store.insert_many(
            [
                _event(agent_id="agent-a", usage=TokenUsage(total_tokens=10)),
                _event(agent_id="agent-a", usage=TokenUsage(total_tokens=5)),
                _event(agent_id="agent-b", usage=TokenUsage(total_tokens=7)),
            ]
        )
        app = _build_app(store, tmp_path)
        client = TestClient(app)
        response = client.get(
            "/api/v1/usage/models/summary", params={"group_by": "agent_id"}, headers=AUTH_HEADERS
        )
        assert response.status_code == 200
        by_agent = {row["agent_id"]: row for row in response.json()}
        assert by_agent["agent-a"]["total_tokens"] == 15
        assert by_agent["agent-b"]["total_tokens"] == 7
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_summary_endpoint_filters_by_time_range(tmp_path) -> None:
    from fastapi.testclient import TestClient

    store = UsageStore(":memory:")
    await store.start()
    try:
        await store.insert_many(
            [
                _event(created_at=100, agent_id="early"),
                _event(created_at=900, agent_id="late"),
            ]
        )
        app = _build_app(store, tmp_path)
        client = TestClient(app)
        response = client.get(
            "/api/v1/usage/models/summary",
            params={"from": 0, "to": 200, "group_by": "agent_id"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        agents = {row["agent_id"] for row in response.json()}
        assert agents == {"early"}
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_events_endpoint_returns_paginated_raw_events(tmp_path) -> None:
    from fastapi.testclient import TestClient

    store = UsageStore(":memory:")
    await store.start()
    try:
        await store.insert_many(
            [
                _event(event_id="e1", created_at=100),
                _event(event_id="e2", created_at=200),
            ]
        )
        app = _build_app(store, tmp_path)
        client = TestClient(app)
        page1 = client.get(
            "/api/v1/usage/models/events", params={"limit": 1, "offset": 0}, headers=AUTH_HEADERS
        )
        page2 = client.get(
            "/api/v1/usage/models/events", params={"limit": 1, "offset": 1}, headers=AUTH_HEADERS
        )
        assert page1.json()[0]["event_id"] == "e2"  # created_at DESC
        assert page2.json()[0]["event_id"] == "e1"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_events_endpoint_rejects_limit_over_500(tmp_path) -> None:
    from fastapi.testclient import TestClient

    store = UsageStore(":memory:")
    await store.start()
    try:
        app = _build_app(store, tmp_path)
        client = TestClient(app)
        response = client.get(
            "/api/v1/usage/models/events", params={"limit": 501}, headers=AUTH_HEADERS
        )
        assert response.status_code == 422
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_timeseries_endpoint_groups_by_hour_bucket(tmp_path) -> None:
    from fastapi.testclient import TestClient

    store = UsageStore(":memory:")
    await store.start()
    try:
        hour1 = 1_700_000_000
        hour2 = hour1 + 3600
        await store.insert_many(
            [
                _event(created_at=hour1),
                _event(created_at=hour1 + 100),
                _event(created_at=hour2),
            ]
        )
        app = _build_app(store, tmp_path)
        client = TestClient(app)
        response = client.get(
            "/api/v1/usage/models/timeseries", params={"bucket": "hour"}, headers=AUTH_HEADERS
        )
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 2
        assert all("time_bucket" in row for row in rows)
        assert sorted(row["request_count"] for row in rows) == [1, 2]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_timeseries_endpoint_combines_time_bucket_with_extra_group_by(tmp_path) -> None:
    """额外指定 group_by 时应与 time_bucket 一起分组, 而不是互相覆盖或产生重复列报错。"""
    from fastapi.testclient import TestClient

    store = UsageStore(":memory:")
    await store.start()
    try:
        await store.insert_many(
            [
                _event(agent_id="agent-a", created_at=100),
                _event(agent_id="agent-b", created_at=100),
            ]
        )
        app = _build_app(store, tmp_path)
        client = TestClient(app)
        response = client.get(
            "/api/v1/usage/models/timeseries",
            params={"group_by": "agent_id", "bucket": "hour"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 2
        assert {row["agent_id"] for row in rows} == {"agent-a", "agent-b"}
        assert all("time_bucket" in row for row in rows)
    finally:
        await store.stop()
