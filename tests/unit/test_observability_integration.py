"""可观测性端到端集成测试 (CODE_REVIEW_REPORT.md #5)。

test_observability.py 已经覆盖 MetricsCollector/AlertManager 自身的单元行为;
这里验证生产链路 (process_message / ProviderManager.chat_with_retry) 真的调用了
这些埋点, 而不仅仅是组件本身"能被正确调用"——修复前生产链路完全没有接线, /metrics
只会返回初始零值, 默认告警规则永远不会真正触发。
"""

from __future__ import annotations

import asyncio

import pytest

from isac.channel.model import ISACMessage
from isac.channel.registry import ChannelRegistry
from isac.core.exceptions import LLMError
from isac.gateway.event_bus import EventBus
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.main import process_message
from isac.observability import AlertManager, get_default_alert_rules, get_default_metrics
from isac.provider.manager import ProviderManager
from isac.router.router import MessageRouter
from isac.router.types import RoutingRules


class _RecordingAgentManager:
    """模拟 AgentManager: handle_message() 总是返回一条固定回复。"""

    async def handle_message(self, agent_id, message, session, user_profile):
        return "已收到"


def _make_message(content: str) -> ISACMessage:
    return ISACMessage(
        msg_id="m1", platform="webchat", timestamp=0, user_id="u1", user_name="Alice", content=content
    )


@pytest.mark.asyncio
async def test_process_message_increments_received_and_processed_counters() -> None:
    metrics = get_default_metrics()
    router = MessageRouter(RoutingRules(default_agents={"webchat": "default"}), agents_provider=lambda: [])

    await process_message(
        _make_message("你好"),
        event_bus=EventBus(),
        router=router,
        session_mgr=SessionManager({}),
        user_mapper=UserMapper(),
        agent_manager=_RecordingAgentManager(),
        channel_registry=ChannelRegistry(),
        metrics=metrics,
    )

    assert metrics.counter("isac_messages_received_total").value() == 1
    assert metrics.counter("isac_messages_processed_total").value() == 1
    assert metrics.counter("isac_messages_dropped_total").value() == 0


@pytest.mark.asyncio
async def test_process_message_dropped_when_router_has_no_match() -> None:
    metrics = get_default_metrics()
    router = MessageRouter(RoutingRules(), agents_provider=lambda: [])  # 无绑定/无默认 Agent → 无匹配

    await process_message(
        _make_message("你好"),
        event_bus=EventBus(),
        router=router,
        session_mgr=SessionManager({}),
        user_mapper=UserMapper(),
        agent_manager=_RecordingAgentManager(),
        channel_registry=ChannelRegistry(),
        metrics=metrics,
    )

    assert metrics.counter("isac_messages_received_total").value() == 1
    assert metrics.counter("isac_messages_dropped_total").value() == 1
    assert metrics.counter("isac_messages_processed_total").value() == 0


class _RaisingAgentManager:
    """模拟 AgentManager: handle_message() 总是抛出未处理异常。"""

    async def handle_message(self, agent_id, message, session, user_profile):
        raise RuntimeError("模拟 Agent 处理崩溃")


@pytest.mark.asyncio
async def test_process_message_failed_when_agent_handling_raises() -> None:
    metrics = get_default_metrics()
    router = MessageRouter(RoutingRules(default_agents={"webchat": "default"}), agents_provider=lambda: [])

    with pytest.raises(RuntimeError):
        await process_message(
            _make_message("你好"),
            event_bus=EventBus(),
            router=router,
            session_mgr=SessionManager({}),
            user_mapper=UserMapper(),
            agent_manager=_RaisingAgentManager(),
            channel_registry=ChannelRegistry(),
            metrics=metrics,
        )

    assert metrics.counter("isac_messages_received_total").value() == 1
    assert metrics.counter("isac_messages_failed_total").value() == 1
    assert metrics.counter("isac_messages_processed_total").value() == 0


class _AlwaysFailsProvider:
    """模拟持续失败的 LLM Provider, 每次调用都抛 LLMError。"""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, **kwargs):
        self.calls += 1
        raise LLMError("模拟持续失败")

    async def chat_stream(self, *args, **kwargs):
        raise NotImplementedError

    def get_model_name(self) -> str:
        return "always-fails"

    def get_capabilities(self):
        return None


@pytest.mark.asyncio
async def test_llm_errors_accumulate_and_trigger_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 报错经 chat_with_retry() 累积到阈值后, AlertManager.check_once() 应触发对应告警。"""

    async def _instant_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    provider = _AlwaysFailsProvider()

    # 4 轮调用 * 3 次重试 = 12 次 isac_llm_calls_total, 全部失败 → 错误率 100% > 10% 阈值
    # (llm_error_rate_high 规则要求 total >= 10 才生效)。
    for _ in range(4):
        await provider_manager.chat_with_retry(provider, system="s", messages=[])

    assert metrics.counter("isac_llm_calls_total").value() == 12
    assert metrics.counter("isac_llm_errors_total").value() == 12

    alert_manager = AlertManager(metrics)
    for rule in get_default_alert_rules():
        alert_manager.add_rule(rule)

    fired = await alert_manager.check_once()

    assert any(alert["rule"] == "llm_error_rate_high" for alert in fired)
