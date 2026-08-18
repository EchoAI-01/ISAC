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


@pytest.mark.asyncio
async def test_setup_webhooks_dispatch_does_not_block_event_bus() -> None:
    """Fix-55: 死/慢订阅的推送不得卡住 fire_async —— 它在会话锁内的
    process_message 末尾被 await, 阻塞 = 该会话每条消息等待推送重试退避。
    改为后台任务推送后, fire_async 应立即返回。"""
    import asyncio

    from isac.core.events import EventType
    from isac.gateway.event_bus import EventBus
    from isac.main import _setup_webhooks

    event_bus = EventBus()
    manager = _setup_webhooks(event_bus)

    async def _slow_dispatch(event: str, payload: dict) -> None:
        await asyncio.sleep(1.0)  # 模拟死订阅的重试退避耗时

    manager.dispatch = _slow_dispatch  # type: ignore[method-assign]
    loop = asyncio.get_event_loop()
    start = loop.time()
    await asyncio.wait_for(
        event_bus.fire_async(EventType.POST_MESSAGE, {"x": 1}), timeout=2.0
    )
    elapsed = loop.time() - start
    assert elapsed < 0.5  # 立即返回, 不等后台推送
    await asyncio.sleep(1.2)  # 让后台推送任务跑完, 避免悬挂 task 警告


@pytest.mark.asyncio
async def test_legacy_event_names_normalize_to_spec_catalog() -> None:
    """Fix-80: 事件名以 CONTROL_PLANE_SPEC §5.1 目录为准 —— 旧名 (post_message/
    post_send) 订阅与规范名 (message.*) 派发互通, 此前按文档订阅 message.* 永远
    收不到以 EventBus 枚举值派发的事件。"""
    http = _MockHTTPClient()
    mgr = WebhookManager(http_client=http)

    # 按规范目录名订阅, 旧名派发必须送达
    mgr.subscribe("message.responded", "https://a.com/hook")
    result = await mgr.dispatch("post_message", {"x": 1})
    assert result == {"https://a.com/hook": "ok"}

    # 旧名订阅, 规范名派发也必须送达 (订阅清单按规范名归一)
    mgr.subscribe("post_send", "https://b.com/hook")
    assert "message.sent" in mgr.list_subscriptions()
    result = await mgr.dispatch("message.sent", {"y": 2})
    assert result == {"https://b.com/hook": "ok"}

    events = [json.loads(payload)["event"] for _url, payload in http.calls]
    assert events == ["message.responded", "message.sent"]  # 推送体用规范名
