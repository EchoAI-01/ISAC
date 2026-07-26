"""P0: 消息处理并发化集成测试 (DEVELOPMENT_PLAN.md §四 P0)。

验收对应:
- 跨会话并发: 不同会话的消息真并行处理 (LLM 调用时间窗重叠)
- 单会话串行: 同一会话消息按到达顺序串行处理, 回复顺序不乱
- 优雅关闭: drain_inflight 等待在途任务完成, 不丢已接收的消息
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from isac.channel.model import MessageSegment
from isac.channel.registry import ChannelRegistry
from isac.core.types import LLMResponse
from isac.gateway.event_bus import EventBus
from isac.gateway.lock import SessionLockManager
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.main import make_message_dispatcher
from isac.memory.pipeline import NoOpMemoryPipeline
from isac.observability import get_default_metrics
from isac.provider.manager import ProviderManager
from isac.router.router import MessageRouter
from isac.router.types import RoutingRules
from isac.runtime.config import AgentConfig
from isac.runtime.manager import AgentManager
from tests.fixtures.fakes import FakeChannel, FakeLLMProvider, make_final_reply


class SlowFakeProvider(FakeLLMProvider):
    """带固定延迟的 Fake Provider, 并记录并发峰值 (验证并行/串行语义)。"""

    def __init__(self, *, delay: float, scripted_replies: list[LLMResponse] | None = None) -> None:
        super().__init__(scripted_replies=scripted_replies)
        self._delay = delay
        self._active = 0
        self.max_concurrency = 0

    async def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs: Any):
        self._active += 1
        self.max_concurrency = max(self.max_concurrency, self._active)
        try:
            await asyncio.sleep(self._delay)
            return await super().chat(system, messages, tools, **kwargs)
        finally:
            self._active -= 1


async def _build_env(provider: FakeLLMProvider):
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    provider_manager.register(provider)
    services: dict[str, Any] = {
        "global_config": {},
        "provider_manager": provider_manager,
        "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
        "metrics": metrics,
    }
    agent_manager = AgentManager(services)
    await agent_manager.create(AgentConfig(agent_id="a", display_name="A"))
    await agent_manager.start("a")

    router = MessageRouter(
        RoutingRules(default_agents={"fake": "a"}), agents_provider=agent_manager.routing_infos
    )
    channel_registry = ChannelRegistry()
    fake_channel = FakeChannel()
    channel_registry.register(fake_channel)

    handle_message, drain_inflight = make_message_dispatcher(
        event_bus=EventBus(),
        router=router,
        session_mgr=SessionManager({}),
        user_mapper=UserMapper(),
        agent_manager=agent_manager,
        channel_registry=channel_registry,
        metrics=metrics,
        session_lock=SessionLockManager(),
        drain_timeout_seconds=10.0,
    )
    fake_channel.on_message = handle_message
    return fake_channel, drain_inflight, provider


async def _inject(channel: FakeChannel, content: str, *, user_id: str) -> None:
    """带 at 段注入消息 (has_at → 门控强制 TRIGGER, 避免回复必要性评分不确定性)。"""
    await channel.receive_inject(
        content,
        user_id=user_id,
        segments=[
            MessageSegment(type="at", data={}),
            MessageSegment(type="text", data={"text": content}),
        ],
    )


@pytest.mark.asyncio
async def test_cross_session_messages_run_concurrently() -> None:
    """不同会话 (不同用户) 的消息并行处理: Provider 并发峰值 >= 2。"""
    provider = SlowFakeProvider(delay=0.15)
    channel, drain, _ = await _build_env(provider)

    await _inject(channel, "你好", user_id="alice")
    await _inject(channel, "你好", user_id="bob")  # handle_message 立即返回, 不被 alice 阻塞
    await drain()

    assert provider.max_concurrency >= 2  # 两条消息的 LLM 调用时间窗重叠 = 真并行
    assert len(channel.replies) == 2


@pytest.mark.asyncio
async def test_same_session_messages_stay_serial_and_ordered() -> None:
    """同一会话消息串行 (并发峰值恒 1) 且回复按到达顺序。"""
    provider = SlowFakeProvider(
        delay=0.05,
        scripted_replies=[make_final_reply("第一条回复"), make_final_reply("第二条回复")],
    )
    channel, drain, _ = await _build_env(provider)

    await _inject(channel, "先发的", user_id="alice")
    await _inject(channel, "后发的", user_id="alice")
    await drain()

    assert provider.max_concurrency == 1  # 会话锁保证同会话不并行
    assert [r.content for r in channel.replies] == ["第一条回复", "第二条回复"]


@pytest.mark.asyncio
async def test_drain_waits_for_inflight_messages() -> None:
    """优雅关闭: handle_message 立即返回, drain 等待在途任务完成后回复必达。"""
    provider = SlowFakeProvider(delay=0.2)
    channel, drain, _ = await _build_env(provider)

    await _inject(channel, "慢消息", user_id="alice")
    assert channel.replies == []  # 派生任务后立即返回, 处理尚未完成

    await drain()
    assert len(channel.replies) == 1  # drain 等到在途消息处理完, 不丢消息
