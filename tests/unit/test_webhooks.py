"""G3 Webhooks 测试 - 订阅 + 推送 + 重试 + trigger。"""

from __future__ import annotations

import json

import pytest

from isac.control.webhooks import WebhookManager


class _MockHTTPClient:
    """记录 POST 调用, 按预设返回。"""

    def __init__(self, responses: dict[str, bool] | None = None) -> None:
        self.calls: list[tuple[str, bytes]] = []
        self.responses = responses or {}

    async def post(self, url: str, payload: bytes) -> bool:
        self.calls.append((url, payload))
        # 默认 True; 如果 url 在 responses 里 False 则返回 False (触发重试)
        return self.responses.get(url, True)


class TestSubscribe:
    def test_subscribe_adds_url(self) -> None:
        mgr = WebhookManager(http_client=_MockHTTPClient())
        mgr.subscribe("agent.created", "https://example.com/hook")
        subs = mgr.list_subscriptions()
        assert "agent.created" in subs
        assert subs["agent.created"] == ["https://example.com/hook"]

    def test_subscribe_multiple_urls(self) -> None:
        mgr = WebhookManager(http_client=_MockHTTPClient())
        mgr.subscribe("agent.created", "https://a.com/hook")
        mgr.subscribe("agent.created", "https://b.com/hook")
        subs = mgr.list_subscriptions("agent.created")
        assert len(subs["agent.created"]) == 2

    def test_unsubscribe_removes_url(self) -> None:
        mgr = WebhookManager(http_client=_MockHTTPClient())
        mgr.subscribe("agent.created", "https://a.com/hook")
        mgr.unsubscribe("agent.created", "https://a.com/hook")
        subs = mgr.list_subscriptions("agent.created")
        assert subs["agent.created"] == []

    def test_unsubscribe_unknown_url_no_op(self) -> None:
        mgr = WebhookManager(http_client=_MockHTTPClient())
        mgr.subscribe("agent.created", "https://a.com/hook")
        mgr.unsubscribe("agent.created", "https://unknown.com/hook")  # 不抛异常
        assert len(mgr.list_subscriptions()["agent.created"]) == 1


class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_no_subscribers_returns_empty(self) -> None:
        mgr = WebhookManager(http_client=_MockHTTPClient())
        result = await mgr.dispatch("agent.created", {"agent_id": "a1"})
        assert result == {}

    @pytest.mark.asyncio
    async def test_dispatch_pushes_to_all_subscribers(self) -> None:
        http = _MockHTTPClient()
        mgr = WebhookManager(http_client=http)
        mgr.subscribe("agent.created", "https://a.com/hook")
        mgr.subscribe("agent.created", "https://b.com/hook")

        result = await mgr.dispatch("agent.created", {"agent_id": "a1"})

        assert result["https://a.com/hook"] == "ok"
        assert result["https://b.com/hook"] == "ok"
        assert len(http.calls) == 2
        # 验证 payload 含 event + data
        for url, payload in http.calls:
            data = json.loads(payload)
            assert data["event"] == "agent.created"
            assert data["data"]["agent_id"] == "a1"

    @pytest.mark.asyncio
    async def test_dispatch_retries_on_failure(self) -> None:
        http = _MockHTTPClient(responses={"https://a.com/hook": False})
        mgr = WebhookManager(
            http_client=http,
            max_retries=3,
            retry_backoff=0.01,  # 测试快一点
        )
        mgr.subscribe("agent.created", "https://a.com/hook")

        result = await mgr.dispatch("agent.created", {"agent_id": "a1"})

        assert "failed" in result["https://a.com/hook"]
        # 重试 3 次
        assert len(http.calls) == 3

    @pytest.mark.asyncio
    async def test_dispatch_partial_failure(self) -> None:
        http = _MockHTTPClient(
            responses={"https://good.com/hook": True, "https://bad.com/hook": False}
        )
        mgr = WebhookManager(
            http_client=http, max_retries=2, retry_backoff=0.01
        )
        mgr.subscribe("agent.created", "https://good.com/hook")
        mgr.subscribe("agent.created", "https://bad.com/hook")

        result = await mgr.dispatch("agent.created", {"agent_id": "a1"})

        assert result["https://good.com/hook"] == "ok"
        assert "failed" in result["https://bad.com/hook"]


class TestTrigger:
    @pytest.mark.asyncio
    async def test_trigger_dispatches_to_subscribers(self) -> None:
        http = _MockHTTPClient()
        mgr = WebhookManager(http_client=http)
        mgr.subscribe("custom.event", "https://example.com/hook")

        result = await mgr.trigger("custom.event", {"key": "value"})

        assert result["https://example.com/hook"] == "ok"
        assert len(http.calls) == 1
