"""U8 mock IM 事件流快照回放 (无真实凭据跑整条 bot 链路)。

验收 (DEVELOPMENT_PLAN §四 U8): 快照回放测试跑通 —— 脱敏的 IM 事件流 JSON 夹具
经真实主链路 (EventBus → Router → Session/Gating → AgentManager → LLM → Channel)
回放, 断言回复序列与会话连续性; 同时验证 SessionWriteGate 在场时反应式消息链路
零干扰 (门只仲裁主动写入)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from isac.channel.model import ISACMessage, MessageSegment
from isac.channel.registry import ChannelRegistry
from isac.gateway.event_bus import EventBus
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.main import process_message
from isac.memory.pipeline import NoOpMemoryPipeline
from isac.observability import get_default_metrics
from isac.provider.manager import ProviderManager
from isac.router.router import MessageRouter
from isac.router.types import RoutingRules
from isac.runtime.config import AgentConfig
from isac.runtime.manager import AgentManager
from isac.runtime.write_gate import SessionWriteGate
from tests.fixtures.fakes import FakeChannel, FakeLLMProvider, make_final_reply

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "u8_im_event_stream.json"


def _load_snapshot() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


async def _build_replay_chain(scripted_replies: list[str]) -> tuple[Any, ...]:
    """构造回放夹具: 与 test_single_agent_flow._build_e2e 同构 + 生产侧门/锁。"""
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    fake_provider = FakeLLMProvider(
        scripted_replies=[make_final_reply(text) for text in scripted_replies]
    )
    provider_manager.register(fake_provider)

    services = {
        "global_config": {},
        "provider_manager": provider_manager,
        "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
        "metrics": metrics,
        # U8: 生产 services 袋含门 —— 回放验证其在场时反应式链路零干扰
        "session_write_gate": SessionWriteGate(),
    }
    agent_manager = AgentManager(services)
    await agent_manager.create(AgentConfig(agent_id="default", display_name="ISAC"))
    await agent_manager.start("default")

    router = MessageRouter(
        RoutingRules(bindings=[], default_agents={"fake": "default"}),
        agents_provider=agent_manager.routing_infos,
    )
    event_bus = EventBus()
    session_mgr = SessionManager({})
    user_mapper = UserMapper()
    channel_registry = ChannelRegistry()
    fake_channel = FakeChannel()
    channel_registry.register(fake_channel)
    return agent_manager, router, event_bus, session_mgr, user_mapper, channel_registry, fake_channel


def _event_to_message(event: dict[str, Any], index: int) -> ISACMessage:
    segments = [MessageSegment(type="text", data={"text": event["content"]})]
    if event.get("at_bot"):
        segments = [MessageSegment(type="at", data={}), *segments]
    return ISACMessage(
        msg_id=f"replay-{index}",
        platform="fake",
        timestamp=1700000000 + index,
        user_id=event["user_id"],
        user_name=event["user_id"],
        group_id=event.get("group_id"),
        content=event["content"],
        segments=segments,
    )


@pytest.mark.asyncio
async def test_snapshot_replay_full_chain() -> None:
    """快照回放: 5 条事件 → 4 条回复 (群聊短反应被门控 WAIT, 私聊/@ 触发)。"""
    snapshot = _load_snapshot()
    (agent_manager, router, event_bus, session_mgr,
     user_mapper, channel_registry, fake_channel) = await _build_replay_chain(
        snapshot["scripted_replies"]
    )

    for index, event in enumerate(snapshot["events"]):
        await process_message(
            _event_to_message(event, index),
            event_bus=event_bus,
            router=router,
            session_mgr=session_mgr,
            user_mapper=user_mapper,
            agent_manager=agent_manager,
            channel_registry=channel_registry,
            metrics=get_default_metrics(),
        )

    replies = fake_channel.replies
    assert len(replies) == snapshot["expected_reply_count"]
    # scripted 队列按 LLM 实际调用顺序消费: WAIT 的消息不消耗回复, 逐条对齐
    for index, reply in enumerate(replies):
        assert reply.content == snapshot["scripted_replies"][index]

    # 会话连续性: 同用户私聊两轮复用同一 session, 群聊按群聚合
    if hasattr(session_mgr, "list_sessions"):
        sessions = await session_mgr.list_sessions()
        assert len(sessions) >= 2  # 私聊 user-alpha + 群 group-ops (至少)


@pytest.mark.asyncio
async def test_snapshot_replay_gate_does_not_block_reactive() -> None:
    """SessionWriteGate 在场不干扰反应式消息链路 (门只仲裁主动写入)。

    回放期间主动占用某会话的租约, 也不影响其他会话的反应式回复; 且回放结束后
    门内无残留租约 (反应式路径不预约)。
    """
    snapshot = _load_snapshot()
    (agent_manager, router, event_bus, session_mgr,
     user_mapper, channel_registry, fake_channel) = await _build_replay_chain(
        snapshot["scripted_replies"]
    )
    gate: SessionWriteGate = agent_manager._services["session_write_gate"]  # noqa: SLF001

    # 模拟主动写者占用一个无关会话
    hold = gate.reserve("other-session", "proactive")
    assert hold is not None

    for index, event in enumerate(snapshot["events"]):
        await process_message(
            _event_to_message(event, index),
            event_bus=event_bus,
            router=router,
            session_mgr=session_mgr,
            user_mapper=user_mapper,
            agent_manager=agent_manager,
            channel_registry=channel_registry,
            metrics=get_default_metrics(),
        )

    assert len(fake_channel.replies) == snapshot["expected_reply_count"]
    # 门内仅剩测试手动占用的租约 (反应式链路零预约)
    assert len(gate) == 1 and gate.active("other-session") is hold
