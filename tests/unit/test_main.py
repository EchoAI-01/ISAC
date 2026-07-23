"""main.py process_message() 消息主链路测试。

覆盖两个已知缺陷 (CODE_REVIEW_REPORT.md #7/#8)：
- EventBus intercept 返回的替换 payload 必须真正生效，而不是被丢弃。
- 路由剥离触发词后的 content 必须传给 Agent，而不是原始未剥离的内容。
"""

from __future__ import annotations

import pytest

from isac.channel.model import ISACMessage
from isac.channel.registry import ChannelRegistry
from isac.core.events import EventType
from isac.gateway.event_bus import EventBus
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.main import process_message
from isac.router.router import MessageRouter
from isac.router.types import RoutingRules


class _RecordingAgentManager:
    """记录 handle_message() 实际收到的 message，供断言使用。"""

    def __init__(self) -> None:
        self.received_messages: list[ISACMessage] = []

    async def handle_message(self, agent_id, message, session, user_profile):
        self.received_messages.append(message)
        return None


class _StaticAgentsProvider:
    """满足 AgentsProvider 协议的最小实现，供 MessageRouter 触发词匹配。"""

    def __init__(self, agent_id: str, trigger_words: list[str]) -> None:
        self.agent_id = agent_id
        self.trigger_words = trigger_words

    def __call__(self):
        return [self]


def _make_message(content: str) -> ISACMessage:
    return ISACMessage(
        msg_id="m1",
        platform="webchat",
        timestamp=0,
        user_id="u1",
        user_name="Alice",
        content=content,
    )


@pytest.mark.asyncio
async def test_intercept_replacement_payload_reaches_agent() -> None:
    """intercept handler 返回替换后的 message，下游 Agent 应收到替换后的内容。"""
    event_bus = EventBus()
    replaced = _make_message("已被插件替换的内容")

    async def _replace(_payload: ISACMessage) -> ISACMessage:
        return replaced

    event_bus.on_intercept(EventType.ON_MESSAGE, _replace)

    router = MessageRouter(RoutingRules(default_agents={"webchat": "default"}), agents_provider=lambda: [])
    agent_manager = _RecordingAgentManager()

    await process_message(
        _make_message("原始内容"),
        event_bus=event_bus,
        router=router,
        session_mgr=SessionManager({}),
        user_mapper=UserMapper(),
        agent_manager=agent_manager,
        channel_registry=ChannelRegistry(),
    )

    assert len(agent_manager.received_messages) == 1
    assert agent_manager.received_messages[0].content == "已被插件替换的内容"


@pytest.mark.asyncio
async def test_trigger_word_stripped_content_reaches_agent() -> None:
    """路由匹配触发词后剥离出的 content，应是 Agent 实际收到的内容，而非原始文本。"""
    event_bus = EventBus()
    agents_provider = _StaticAgentsProvider(agent_id="bot_a", trigger_words=["/bot_a "])
    router = MessageRouter(RoutingRules(), agents_provider=agents_provider)
    agent_manager = _RecordingAgentManager()

    await process_message(
        _make_message("/bot_a 你好呀"),
        event_bus=event_bus,
        router=router,
        session_mgr=SessionManager({}),
        user_mapper=UserMapper(),
        agent_manager=agent_manager,
        channel_registry=ChannelRegistry(),
    )

    assert len(agent_manager.received_messages) == 1
    assert agent_manager.received_messages[0].content == "你好呀"
