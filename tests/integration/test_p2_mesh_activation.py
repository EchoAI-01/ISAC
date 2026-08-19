"""P2: Mesh 激活集成测试 (DEVELOPMENT_PLAN.md §四 P2)。

验收对应:
- observer 旁听: 只入记忆不回复
- candidate 仲裁: 评分显著更高才切换回复者 (SWITCH_MARGIN)
- notify: Link 授予 notify 权限后真实投递到目标 Agent
- handoff: 摘要送达接手方 + 会话归属真实转移 (后续消息路由给接手方)
- memory_query: 同步取回目标 Agent 按 scope 裁剪的记忆检索结果
- 无 mesh_role / 无 permissions 配置时零行为变化 (deny-by-default)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from isac.channel.model import ISACMessage, MessageSegment
from isac.channel.registry import ChannelRegistry
from isac.gateway.event_bus import EventBus
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.main import _answer_memory_query, _apply_mesh_routing, process_message
from isac.memory.embedder import EmbeddingManager
from isac.memory.pipeline import MemoryRetrievalPipeline, NoOpMemoryPipeline
from isac.memory.storage.graph import GraphStore
from isac.memory.storage.metadata import MetadataStore
from isac.memory.storage.sparse import SparseBM25Index
from isac.memory.storage.vector import VectorStore
from isac.observability import get_default_metrics
from isac.provider.manager import ProviderManager
from isac.router.router import MessageRouter
from isac.router.types import RoutingDecision, RoutingRules
from isac.runtime.bus import InterAgentBus, InterAgentLink, InterAgentMessage
from isac.runtime.config import AgentConfig
from isac.runtime.manager import AgentManager
from isac.runtime.mesh.actions import MeshActionBroker
from isac.runtime.services import ServiceContainer
from tests.fixtures.fakes import FakeChannel, FakeLLMProvider, make_final_reply


def _real_memory_factory(tmp_path: Path):
    metadata_store = MetadataStore(str(tmp_path / "metadata.db"))
    sparse_indexes: dict[str, SparseBM25Index] = {}

    def factory(namespace: str) -> MemoryRetrievalPipeline:
        return MemoryRetrievalPipeline(
            namespace=namespace,
            metadata=metadata_store,
            vector=VectorStore(str(tmp_path / f"vectors-{namespace}.db")),
            sparse=sparse_indexes.setdefault(namespace, SparseBM25Index()),
            graph=GraphStore(str(tmp_path / "graph.db")),
            embedder=EmbeddingManager({}),
            reranker=None,
        )

    return factory, metadata_store


async def _build_env(
    *,
    agents: list[AgentConfig],
    llm_replies=None,
    tmp_path: Path | None = None,
    default_agent: str = "a",
):
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    provider = FakeLLMProvider(scripted_replies=llm_replies or [make_final_reply("ok")])
    provider_manager.register(provider)
    if tmp_path is not None:
        memory_factory, metadata_store = _real_memory_factory(tmp_path)
        await metadata_store.init_schema()
    else:
        memory_factory, metadata_store = (lambda ns: NoOpMemoryPipeline(ns)), None

    bus = InterAgentBus()
    services: dict[str, Any] = {
        "global_config": {},
        "provider_manager": provider_manager,
        "memory_factory": memory_factory,
        "metrics": metrics,
        "bus": bus,
    }
    agent_manager = AgentManager(services)
    for config in agents:
        await agent_manager.create(config)
        await agent_manager.start(config.agent_id)

    router = MessageRouter(
        RoutingRules(default_agents={"fake": default_agent}),
        agents_provider=agent_manager.routing_infos,
    )
    services["router"] = router
    session_mgr = SessionManager({})

    async def _deliver(target_agent_id: str, message: InterAgentMessage) -> str | None:
        if message.type == "memory_query":
            return await _answer_memory_query(agent_manager, target_agent_id, message)
        wrapped = ISACMessage(
            msg_id="",
            platform="interagent",
            timestamp=0,
            user_id=message.from_agent,
            user_name="",
            group_id=None,
            content=message.content,
        )
        session = await session_mgr.get_or_create(wrapped, agent_id=target_agent_id)
        return await agent_manager.handle_message(target_agent_id, wrapped, session, None)

    bus.set_deliver(_deliver)

    channel_registry = ChannelRegistry()
    fake_channel = FakeChannel()
    channel_registry.register(fake_channel)
    return agent_manager, router, session_mgr, channel_registry, fake_channel, bus, provider, metadata_store


def _msg(content: str, *, user_id: str = "u1", at: bool = True) -> ISACMessage:
    segments = [MessageSegment(type="text", data={"text": content})]
    if at:
        segments.insert(0, MessageSegment(type="at", data={}))
    return ISACMessage(
        msg_id=f"m-{abs(hash(content)) % 99999}",
        platform="fake",
        timestamp=1,
        user_id=user_id,
        user_name=user_id,
        group_id=None,
        content=content,
        segments=segments,
    )


async def _run(msg, *, am, router, sm, cr) -> None:
    await process_message(
        msg,
        event_bus=EventBus(),
        router=router,
        session_mgr=sm,
        user_mapper=UserMapper(),
        agent_manager=am,
        channel_registry=cr,
        metrics=get_default_metrics(),
    )
    pending = list(am._memory_tasks)  # noqa: SLF001
    if pending:
        await asyncio.gather(*pending)


@pytest.mark.asyncio
async def test_observer_hears_message_without_replying(tmp_path: Path) -> None:
    """observer 旁听: 消息入自己的记忆但不产生回复。"""
    am, router, sm, cr, channel, _bus, provider, metadata_store = await _build_env(
        agents=[
            AgentConfig(agent_id="a", display_name="A"),
            AgentConfig(agent_id="obs", display_name="Obs", mesh_role="observer"),
        ],
        tmp_path=tmp_path,
    )
    await _run(_msg("today_secret_keyword 已经确认"), am=am, router=router, sm=sm, cr=cr)

    assert len(channel.replies) == 1  # 只有 primary 回复
    # observer 的记忆命名空间里有这条旁听记录
    rows = await metadata_store.search_fts("obs", "today_secret_keyword")
    assert len(rows) == 1
    assert rows[0]["content"].startswith("u1:")


@pytest.mark.asyncio
async def test_observer_write_is_backgrounded_not_blocking_primary(monkeypatch) -> None:
    """R2-3: observer 旁听写入不阻塞 primary 回复路径 —— _apply_mesh_routing 调度
    后台任务后立即返回, 慢速旁听写入在 drain 时才完成 (此前是顺序 await 内联)。"""
    am, router, sm, _cr, _channel, _bus, _provider, _ = await _build_env(
        agents=[
            AgentConfig(agent_id="a", display_name="A"),
            AgentConfig(agent_id="obs", display_name="Obs", mesh_role="observer"),
        ],
    )
    observed = {"done": False}

    async def slow_observe(agent_id, message, session, profile) -> None:  # noqa: ANN001
        await asyncio.sleep(0.1)
        observed["done"] = True

    monkeypatch.setattr(am, "observe_message", slow_observe)

    msg = _msg("hello", at=False)
    decision = RoutingDecision(agent_id="a", matched_by="default", content="hello")
    session = await sm.get_or_create(msg, agent_id="a")
    final = await _apply_mesh_routing(decision, msg, session, None, sm, am)

    assert final == "a"  # observer 不改变归属
    assert observed["done"] is False  # 旁听写入被后台化, 未阻塞 _apply_mesh_routing
    assert len(am._memory_tasks) == 1  # noqa: SLF001  已调度为后台任务
    await am.drain_background_tasks()
    assert observed["done"] is True  # drain 等到旁听写入完成


@pytest.mark.asyncio
async def test_candidate_arbitration_switches_on_higher_score() -> None:
    """candidate 评分显著高于 primary (被@点名 display_name) 时接管回复。"""
    replies = [make_final_reply("candidate 的回复")]
    am, router, sm, cr, channel, _bus, provider, _ = await _build_env(
        agents=[
            AgentConfig(agent_id="a", display_name="小助手"),
            # candidate 的 display_name 出现在消息里 → 内容分显著更高
            AgentConfig(agent_id="cand", display_name="天气专家", mesh_role="candidate"),
        ],
        llm_replies=replies,
    )
    # 消息不 @ (避免双方都拿满强制分), 直呼候选者名字 → 候选者 has_mention 内容分高
    await _run(
        _msg("天气专家 明天要带伞吗? 请详细说明理由。", at=False), am=am, router=router, sm=sm, cr=cr
    )

    assert [r.content for r in channel.replies] == ["candidate 的回复"]
    # LLM 只被调用一次 (仲裁在门控评分层完成, 不是两个 Agent 都跑 Loop)
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_no_mesh_roles_keeps_single_primary_routing() -> None:
    """无 Agent 配置 mesh_role → 单主路由零行为变化。"""
    am, router, sm, cr, channel, _bus, provider, _ = await _build_env(
        agents=[AgentConfig(agent_id="a", display_name="A")],
    )
    await _run(_msg("你好"), am=am, router=router, sm=sm, cr=cr)
    assert len(channel.replies) == 1


@pytest.mark.asyncio
async def test_notify_delivers_to_target_agent() -> None:
    """Link 授予 notify 权限后, broker.notify 真实投递并触发目标 Agent 处理。"""
    am, _router, _sm, _cr, _ch, bus, provider, _ = await _build_env(
        agents=[
            AgentConfig(agent_id="a", display_name="A"),
            AgentConfig(agent_id="b", display_name="B"),
        ],
    )
    bus.add_link(InterAgentLink(from_agent="a", to_agent="b", permissions=["notify"]))
    broker = MeshActionBroker(bus)

    ok = await broker.notify("a", "b", "用户提到了你负责的话题")
    assert ok is True
    # 目标 Agent 真实收到 (deliver → handle_message → LLM 被调用)
    assert any("用户提到了你负责的话题" in str(c["messages"]) for c in provider.calls)


@pytest.mark.asyncio
async def test_notify_denied_without_permission() -> None:
    """Link 存在但未授予 notify 权限 → deny-by-default 拒绝。"""
    am, _router, _sm, _cr, _ch, bus, provider, _ = await _build_env(
        agents=[AgentConfig(agent_id="a"), AgentConfig(agent_id="b")],
    )
    bus.add_link(InterAgentLink(from_agent="a", to_agent="b"))  # permissions 默认空
    broker = MeshActionBroker(bus)
    assert await broker.notify("a", "b", "x") is False
    assert provider.calls == []


@pytest.mark.asyncio
async def test_handoff_transfers_session_ownership() -> None:
    """handoff: 摘要送达接手方 + Router 归属转移, 后续消息路由给接手 Agent。"""
    from isac.agent.tools.social.handoff_conversation import HandoffConversationTool
    from isac.core.types import AgentContext
    from isac.gateway.models import Session

    am, router, sm, cr, channel, bus, provider, _ = await _build_env(
        agents=[
            AgentConfig(agent_id="a", display_name="A"),
            AgentConfig(agent_id="b", display_name="B"),
        ],
        llm_replies=[make_final_reply("摘要收到"), make_final_reply("B 接手后的回复")],
    )
    bus.add_link(InterAgentLink(from_agent="a", to_agent="b", permissions=["handoff"]))
    broker = MeshActionBroker(bus)

    # 模拟 Agent a 在会话中调用 handoff_conversation 工具
    tool = HandoffConversationTool()
    session = Session(session_id="s1", user_id="u1", agent_id="a", platform="fake")
    context = type("Ctx", (), {})()
    context.args = {"target_agent": "b", "summary": "用户在问天气, 请接手"}
    context.services = ServiceContainer({"mesh_action_broker": broker, "agent_id": "a", "router": router})
    context.agent_context = AgentContext(
        session=session, user_profile=None, current_message=_msg("x", at=False)
    )
    result = await tool.execute(context)
    assert result.is_error is False
    assert "接手" in result.content
    # 摘要真实送达 b (经 bus deliver → handle_message)
    assert any("用户在问天气" in str(c["messages"]) for c in provider.calls)

    # 归属转移: 该用户的后续消息路由给 b (matched_by=handoff, 优先级最高)
    decision = await router.route(_msg("还在吗", at=False))
    assert decision is not None
    assert decision.agent_id == "b"
    assert decision.matched_by == "handoff"


@pytest.mark.asyncio
async def test_memory_query_returns_scope_trimmed_results(tmp_path: Path) -> None:
    """memory_query: 同步取回目标 Agent 的检索结果, 且按 user scope 真实裁剪。"""
    am, _router, _sm, _cr, _ch, bus, _provider, metadata_store = await _build_env(
        agents=[
            AgentConfig(agent_id="a", display_name="A"),
            AgentConfig(agent_id="b", display_name="B"),
        ],
        tmp_path=tmp_path,
    )
    # b 的记忆里: u1 的私聊记录 + u2 的私聊记录 (同关键词)
    await metadata_store.store_episode(
        "b", {"content": "u1: hiking_plan_alpha 周末去", "session_id": "s1", "user_id": "u1"}
    )
    await metadata_store.store_episode(
        "b", {"content": "u2: hiking_plan_alpha 我也想去", "session_id": "s2", "user_id": "u2"}
    )
    instance_b = await am.get("b")
    await instance_b.memory.warm_up_sparse_index()

    # Link 只授予对 u1 范围的 memory_query
    bus.add_link(
        InterAgentLink(
            from_agent="a", to_agent="b",
            permissions=["memory_query"], visible_memory_scopes=["user:u1"],
        )
    )
    broker = MeshActionBroker(bus)
    response = await broker.memory_query("a", "b", "hiking_plan_alpha")

    assert response is not None and "hiking_plan_alpha" in response
    assert "u1:" in response  # scope 内的内容可见
    assert "u2:" not in response  # scope 外的内容被裁剪
