"""U5 工具权限管线 + HITL 卡片审批全链路集成测试。

验收覆盖 (DEVELOPMENT_PLAN §四 U5): ask 审批完整闭环三路 (卡片同意/拒绝/超时
fail-closed), 经真实 process_message 主链路: LLM tool_call → ask 档拦截 → 审批卡片
投递 FakeChannel → IM 回复 "同意/拒绝 <审批码>" 被 process_message 拦截回流 →
gate.decide → 工具执行/拒绝 → 决策留痕 U1 事件表。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from isac.agent.tools.approval import ApprovalGate
from isac.agent.tools.guard import OUTCOME_DENIED, DenyGuard
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
from isac.session.event_store import SessionEventStore
from isac.session.history import SessionHistoryDeriver
from tests.fixtures.fakes import FakeChannel, FakeLLMProvider, make_final_reply, make_tool_call_response

SESSION_KEY = "default:fake:group:g1"


async def _build_hitl_harness(tmp_path: Path, *, gate_timeout: float = 5.0):
    """构造带 U5 审批接线的 E2E 夹具 (query_memory 配置为 ask 档)。"""
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    provider = FakeLLMProvider()
    provider_manager.register(provider)

    session_mgr = SessionManager({})
    store = SessionEventStore(str(tmp_path / "session_events.db"))
    await store.start()
    gate = ApprovalGate(timeout_seconds=gate_timeout)
    guard = DenyGuard()
    channel_registry = ChannelRegistry()
    channel = FakeChannel()
    channel_registry.register(channel)

    services = {
        "global_config": {"session": {"history": {"enabled": True, "window_turns": 5}}},
        "provider_manager": provider_manager,
        "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
        "metrics": metrics,
        "session_mgr": session_mgr,
        "session_event_store": store,
        "session_history": SessionHistoryDeriver(window_turns=5),
        "approval_gate": gate,
        "deny_guard": guard,
        # 卡片投递经 services["channel_registry"] (生产同构); assemble_agent 在
        # create() 时浅拷贝 services, 必须先于 create 注入。
        "channel_registry": channel_registry,
    }
    agent_manager = AgentManager(services)
    await agent_manager.create(
        AgentConfig(
            agent_id="default",
            display_name="ISAC",
            trigger_words=[],
            tools_policy={"query_memory": "ask"},  # U5: 记忆查询升为人工审批档
        )
    )
    await agent_manager.start("default")

    router = MessageRouter(
        RoutingRules(bindings=[], default_agents={"fake": "default"}),
        agents_provider=agent_manager.routing_infos,
    )
    event_bus = EventBus()
    user_mapper = UserMapper()

    return {
        "am": agent_manager, "router": router, "eb": event_bus, "sm": session_mgr,
        "um": user_mapper, "cr": channel_registry, "channel": channel,
        "provider": provider, "store": store, "gate": gate, "guard": guard,
    }


async def _run(h: dict, message: ISACMessage) -> None:
    await process_message(
        message,
        event_bus=h["eb"], router=h["router"], session_mgr=h["sm"], user_mapper=h["um"],
        agent_manager=h["am"], channel_registry=h["cr"], metrics=get_default_metrics(),
    )


def _msg(content: str, *, msg_id: str) -> ISACMessage:
    segments = [MessageSegment(type="at", data={}), MessageSegment(type="text", data={"text": content})]
    return ISACMessage(
        msg_id=msg_id, platform="fake", timestamp=1, user_id="u1", user_name="u1",
        group_id="g1", content=content, segments=segments,
    )


async def _wait_pending(gate: ApprovalGate) -> str:
    for _ in range(200):
        pending = gate.pending_requests()
        if pending:
            return pending[0]["approval_id"]
        await asyncio.sleep(0.01)
    raise AssertionError("审批请求未在 2s 内出现")


@pytest.mark.asyncio
async def test_hitl_approval_full_loop_approved(tmp_path: Path) -> None:
    """同意路: tool_call → 审批卡片 → IM 回复同意 → 工具执行 → 最终回复 + 留痕。"""
    h = await _build_hitl_harness(tmp_path)
    provider, channel, gate, store = h["provider"], h["channel"], h["gate"], h["store"]
    provider.queue_reply(make_tool_call_response("query_memory", arguments={"query": "项目进度"}))
    provider.queue_reply(make_final_reply("查到了"))

    turn_task = asyncio.create_task(_run(h, _msg("@bot 查下记忆", msg_id="m1")))
    approval_id = await _wait_pending(gate)
    # 审批卡片已投递到 Channel
    assert any("审批" in r.content and approval_id in r.content for r in channel.replies)
    # IM 回流: 用户回复 "同意 <审批码>" (经 process_message 拦截, 不触发对话回合)
    await _run(h, _msg(f"同意 {approval_id}", msg_id="m2"))
    await asyncio.wait_for(turn_task, timeout=5.0)
    await h["am"].drain_background_tasks(timeout_seconds=2.0)

    # 最终回复送达; 决策留痕 ask_approved + decider 含平台/用户
    assert any(r.content == "查到了" for r in channel.replies)
    events = await store.fetch(SESSION_KEY)
    called = [e for e in events if e.event_type == "tool.called"]
    assert called and called[0].payload["decision"] == "ask_approved"
    assert called[0].payload["decider"].startswith("human:fake:")
    outcomes = [e for e in events if e.event_type == "tool.outcome"]
    assert any(e.payload.get("outcome") == "ok" for e in outcomes)
    await store.stop()


@pytest.mark.asyncio
async def test_hitl_approval_full_loop_rejected(tmp_path: Path) -> None:
    """拒绝路: IM 回复拒绝 → 工具不执行 + 单调 guard 登记 + 留痕 ask_rejected。"""
    h = await _build_hitl_harness(tmp_path)
    provider, gate, store, guard = h["provider"], h["gate"], h["store"], h["guard"]
    provider.queue_reply(make_tool_call_response("query_memory", arguments={"query": "机密"}))
    provider.queue_reply(make_final_reply("好的不查了"))

    turn_task = asyncio.create_task(_run(h, _msg("@bot 查机密", msg_id="m1")))
    approval_id = await _wait_pending(gate)
    await _run(h, _msg(f"拒绝 {approval_id}", msg_id="m2"))
    await asyncio.wait_for(turn_task, timeout=5.0)
    await h["am"].drain_background_tasks(timeout_seconds=2.0)

    # LLM 收到工具被拒错误后仍给出最终回复; guard 已登记拒绝
    assert any(r.content == "好的不查了" for r in h["channel"].replies)
    assert await guard.is_denied(SESSION_KEY, "query_memory") is True
    events = await store.fetch(SESSION_KEY)
    denied = [
        e for e in events
        if e.event_type == "tool.outcome" and e.payload.get("outcome") == OUTCOME_DENIED
    ]
    assert denied and denied[0].payload["decision"] == "ask_rejected"
    await store.stop()


@pytest.mark.asyncio
async def test_hitl_approval_full_loop_timeout(tmp_path: Path) -> None:
    """超时路: 无人回复 → fail-closed 拒绝 + guard 登记 + 留痕 ask_timeout。"""
    h = await _build_hitl_harness(tmp_path, gate_timeout=0.3)
    provider, store, guard = h["provider"], h["store"], h["guard"]
    provider.queue_reply(make_tool_call_response("query_memory", arguments={"query": "x"}))
    provider.queue_reply(make_final_reply("超时没查成"))

    await asyncio.wait_for(_run(h, _msg("@bot 查一下", msg_id="m1")), timeout=8.0)
    await h["am"].drain_background_tasks(timeout_seconds=2.0)

    assert any(r.content == "超时没查成" for r in h["channel"].replies)
    assert await guard.is_denied(SESSION_KEY, "query_memory") is True
    events = await store.fetch(SESSION_KEY)
    denied = [
        e for e in events
        if e.event_type == "tool.outcome" and e.payload.get("outcome") == OUTCOME_DENIED
    ]
    assert denied and denied[0].payload["decision"] == "ask_timeout"
    await store.stop()


@pytest.mark.asyncio
async def test_hitl_stale_approval_code_continues_as_message(tmp_path: Path) -> None:
    """过期/未知审批码的 '同意 xxx' 不被拦截, 按普通消息继续路由 (不误吞)。"""
    h = await _build_hitl_harness(tmp_path)
    provider = h["provider"]
    provider.queue_reply(make_final_reply("收到"))
    await asyncio.wait_for(_run(h, _msg("同意 nosuchid", msg_id="m1")), timeout=8.0)
    await h["am"].drain_background_tasks(timeout_seconds=2.0)
    # 未被拦截 → 正常对话回合产生回复
    assert any(r.content == "收到" for r in h["channel"].replies)
    await h["store"].stop()


def _msg_from(content: str, *, msg_id: str, user_id: str) -> ISACMessage:
    segments = [MessageSegment(type="at", data={}), MessageSegment(type="text", data={"text": content})]
    return ISACMessage(
        msg_id=msg_id, platform="fake", timestamp=1, user_id=user_id, user_name=user_id,
        group_id="g1", content=content, segments=segments,
    )


@pytest.mark.asyncio
async def test_hitl_approval_third_party_cannot_decide(tmp_path: Path) -> None:
    """Fix-90: 审批卡片 (含审批码) 发回原会话, 群内其他成员可见 —— 非发起人
    回复 '同意 <审批码>' 不得裁决 (此前 decide 只按审批码查表 → HITL 门旁路),
    该回复按普通消息继续路由, 审批仍等待真正发起人。"""
    h = await _build_hitl_harness(tmp_path)
    provider, channel, gate = h["provider"], h["channel"], h["gate"]
    # 三条脚本回复: ① u1 回合的 tool_call (触发审批); ② mallory 抢答消息未被
    # 拦截后按普通消息触发的回合消费; ③ u1 批准后工具执行完的收尾回复。
    provider.queue_reply(make_tool_call_response("query_memory", arguments={"query": "项目进度"}))
    provider.queue_reply(make_final_reply("这是给 mallory 的回复"))
    provider.queue_reply(make_final_reply("查到了"))

    turn_task = asyncio.create_task(_run(h, _msg("@bot 查下记忆", msg_id="m1")))
    approval_id = await _wait_pending(gate)

    # 群内另一成员 mallory 抢答同意 → 不得裁决 (来源用户非发起人), 按普通消息路由
    await asyncio.wait_for(
        _run(h, _msg_from(f"同意 {approval_id}", msg_id="m2", user_id="mallory")), timeout=5.0
    )
    pending = gate.pending_requests()
    assert pending and pending[0]["approval_id"] == approval_id  # 未被 mallory 裁决
    assert any(r.content == "这是给 mallory 的回复" for r in channel.replies)

    # 真正发起人 u1 同意 → 放行, 工具执行, 最终回复送达
    await _run(h, _msg(f"同意 {approval_id}", msg_id="m3"))
    await asyncio.wait_for(turn_task, timeout=5.0)
    await h["am"].drain_background_tasks(timeout_seconds=2.0)
    assert any(r.content == "查到了" for r in channel.replies)
    await h["store"].stop()
