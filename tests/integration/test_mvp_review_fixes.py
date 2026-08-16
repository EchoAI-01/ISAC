"""MVP Review 确认缺陷的回归测试 (DEVELOPMENT_PLAN.md §四 MVP-Fix)。

对应 2026-07-27 MVP 增量多视角审查 (5 维度 + 每条 2 票对抗验证) 确认的 13 项。
每个测试**先复现审查描述的失败场景**, 再断言修复后的正确行为。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from isac.channel.model import ISACMessage, MessageSegment
from isac.channel.registry import ChannelRegistry
from isac.core.types import LLMResponse
from isac.gateway.event_bus import EventBus
from isac.gateway.lock import SessionLockManager
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.main import _answer_memory_query, make_message_dispatcher
from isac.memory.pipeline import NoOpMemoryPipeline
from isac.observability import get_default_metrics
from isac.provider.manager import ProviderManager
from isac.router.router import MessageRouter
from isac.router.types import RoutingRules
from isac.runtime.bus import InterAgentBus, InterAgentLink, InterAgentMessage
from isac.runtime.config import AgentConfig
from isac.runtime.manager import AgentManager
from tests.fixtures.fakes import FakeChannel, FakeLLMProvider, make_final_reply, make_tool_call_response


class SlowFakeProvider(FakeLLMProvider):
    def __init__(self, *, delay: float = 0.0, scripted_replies: list[LLMResponse] | None = None) -> None:
        super().__init__(scripted_replies=scripted_replies)
        self._delay = delay

    async def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs: Any):
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        return await super().chat(system, messages, tools, **kwargs)


async def _build_env(
    provider: FakeLLMProvider,
    *,
    conversation: dict[str, Any] | None = None,
    agents_dir: str | None = None,
):
    """conversation.enabled=true 的 dispatcher + manager + FakeChannel 夹具。"""
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    provider_manager.register(provider)
    conv_config = {"enabled": True, "debounce_seconds": 0.0, **(conversation or {})}
    session_mgr = SessionManager({})
    session_lock = SessionLockManager()
    channel_registry = ChannelRegistry()
    channel = FakeChannel()
    channel_registry.register(channel)
    services: dict[str, Any] = {
        "global_config": {
            "conversation": conv_config,
            # 会话快照落到临时目录, 不污染仓库 data/agents
            "control": {"agents_dir": agents_dir or str(Path(__file__).parent / "_tmp_agents")},
        },
        "provider_manager": provider_manager,
        "memory_factory": lambda ns: NoOpMemoryPipeline(ns),
        "metrics": metrics,
        "session_mgr": session_mgr,
        "session_lock": session_lock,
        "channel_registry": channel_registry,
    }
    agent_manager = AgentManager(services)
    await agent_manager.create(AgentConfig(agent_id="a", display_name="A"))
    await agent_manager.start("a")
    router = MessageRouter(
        RoutingRules(default_agents={"fake": "a"}), agents_provider=agent_manager.routing_infos
    )
    handle_message, drain = make_message_dispatcher(
        event_bus=EventBus(), router=router, session_mgr=session_mgr, user_mapper=UserMapper(),
        agent_manager=agent_manager, channel_registry=channel_registry, metrics=metrics,
        session_lock=session_lock, drain_timeout_seconds=15.0,
    )
    channel.on_message = handle_message
    return agent_manager, channel, drain


async def _inject(channel: FakeChannel, content: str, *, user_id: str = "alice", at: bool = True) -> None:
    segments = [MessageSegment(type="text", data={"text": content})]
    if at:
        segments.insert(0, MessageSegment(type="at", data={}))
    await channel.receive_inject(content, user_id=user_id, segments=segments)


async def _drain_all(am: AgentManager, drain) -> None:
    await drain()
    await am.drain_background_tasks()


# ── high: debounce 突发末条被重复处理 ─────────────────────────


@pytest.mark.asyncio
async def test_message_burst_produces_single_merged_reply(tmp_path: Path) -> None:
    """3 条突发消息只产生一条合并回复 (此前中间条 drain 全部, 末条再独立回复一次)。"""
    provider = SlowFakeProvider(
        scripted_replies=[make_final_reply("合并回复"), make_final_reply("不该出现的第二条")]
    )
    am, channel, drain = await _build_env(
        provider, conversation={"debounce_seconds": 0.2}, agents_dir=str(tmp_path)
    )

    await _inject(channel, "第一句")
    await asyncio.sleep(0.02)
    await _inject(channel, "第二句")
    await asyncio.sleep(0.02)
    await _inject(channel, "第三句")
    await _drain_all(am, drain)

    assert [r.content for r in channel.replies] == ["合并回复"]
    assert len(provider.calls) == 1
    merged = provider.calls[0]["messages"][-1]["content"]
    assert "第一句" in merged and "第二句" in merged and "第三句" in merged


# ── high: 门控只评估末条 → 突发里的 @提及被丢弃 ───────────────


@pytest.mark.asyncio
async def test_gating_sees_at_mention_from_earlier_message_in_burst(tmp_path: Path) -> None:
    """突发里靠前消息带 @, 末条不带 —— 整个突发仍应触发回复 (has_at 取并集)。"""
    provider = SlowFakeProvider(scripted_replies=[make_final_reply("收到")])
    am, channel, drain = await _build_env(
        provider, conversation={"debounce_seconds": 0.2}, agents_dir=str(tmp_path)
    )

    await _inject(channel, "在吗", at=True)  # 带 @
    await asyncio.sleep(0.02)
    await _inject(channel, "嗯", at=False)  # 末条不带 @, 内容也不足以过门控
    await _drain_all(am, drain)

    assert [r.content for r in channel.replies] == ["收到"]


# ── high: 多步(工具)回合中的打断被 InterruptInjector 吞掉 ─────


@pytest.mark.asyncio
async def test_interrupt_during_tool_execution_suppresses_stale_reply(tmp_path: Path) -> None:
    """工具执行期间到达的打断必须抑制旧回复 (此前被下一轮 prompt build 清空)。

    用一个慢工具把打断信号精确落进"两次 prompt build 之间"的窗口 —— 这正是
    InterruptInjector 会先消费掉 interrupt_state 的时机。(不能用 wait 工具:
    它把状态转成 WAITING, 走的是"被新消息唤醒"而非打断路径。)
    """
    from isac.agent.tools.base import Tool, ToolContext
    from isac.core.types import ToolResult

    class SlowProbeTool(Tool):
        @property
        def name(self) -> str:
            return "slow_probe"

        @property
        def description(self) -> str:
            return "测试用慢工具"

        @property
        def parameters(self) -> dict:
            return {"type": "object", "properties": {}}

        async def execute(self, context: ToolContext) -> ToolResult:
            await asyncio.sleep(0.4)
            return ToolResult(content="probe done")

    provider = SlowFakeProvider(
        scripted_replies=[
            make_tool_call_response("slow_probe"),  # 回合 A 第一次 LLM: 触发慢工具
            make_final_reply("新回合的回复"),  # 下一次 LLM 调用消费
        ],
    )
    am, channel, drain = await _build_env(provider, agents_dir=str(tmp_path))
    instance = await am.get("a")
    instance.tools.register(SlowProbeTool())

    await _inject(channel, "帮我查一下")
    await asyncio.sleep(0.2)  # 回合 A 已返回 tool_calls, 慢工具执行中 (0.4s 窗口)
    await _inject(channel, "算了不用了")  # 锁外 notify_incoming → request_interrupt
    await _drain_all(am, drain)

    # 过滤 D9 进度帧, 只看真实回复
    replies = [r.content for r in channel.replies if r.metadata.get("message_kind") != "progress"]
    # 回合 A 被抑制 (不发陈旧回复), 接替的回合 B 正常回复 —— 只有一条
    assert replies == ["新回合的回复"]
    # 且 A 在工具执行后**没有**再浪费一次 LLM 调用 (前置判定即返回):
    # 总调用 = A 的第一次 + B 的一次 = 2
    assert len(provider.calls) == 2


# ── high: 记忆写入任务必须被 drain ────────────────────────────


@pytest.mark.asyncio
async def test_drain_background_tasks_waits_for_memory_writes(tmp_path: Path) -> None:
    """drain_background_tasks 等待在途记忆写入 (此前关机时最后几轮记忆静默丢失)。"""
    from isac.memory.embedder import EmbeddingManager
    from isac.memory.pipeline import MemoryRetrievalPipeline
    from isac.memory.storage.graph import GraphStore
    from isac.memory.storage.metadata import MetadataStore
    from isac.memory.storage.sparse import SparseBM25Index
    from isac.memory.storage.vector import VectorStore

    metadata_store = MetadataStore(str(tmp_path / "metadata.db"))
    await metadata_store.init_schema()
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    provider_manager.register(FakeLLMProvider(scripted_replies=[make_final_reply("好的")]))
    services: dict[str, Any] = {
        "global_config": {},
        "provider_manager": provider_manager,
        "memory_factory": lambda ns: MemoryRetrievalPipeline(
            namespace=ns, metadata=metadata_store,
            vector=VectorStore(str(tmp_path / f"v-{ns}.db")), sparse=SparseBM25Index(),
            graph=GraphStore(str(tmp_path / "g.db")), embedder=EmbeddingManager({}), reranker=None,
        ),
        "metrics": metrics,
    }
    am = AgentManager(services)
    await am.create(AgentConfig(agent_id="a", display_name="A"))
    await am.start("a")

    from isac.gateway.models import Session

    msg = ISACMessage(
        msg_id="m1", platform="fake", timestamp=1, user_id="u1", user_name="u1",
        group_id=None, content="记住 drain_keyword_test",
        segments=[MessageSegment(type="at", data={}), MessageSegment(type="text", data={"text": "x"})],
    )
    session = Session(session_id="s1", user_id="u1", agent_id="a", platform="fake")
    await am.handle_message("a", msg, session, None)

    await am.drain_background_tasks()  # 关闭链调用点
    rows = await metadata_store.search_fts("a", "drain_keyword_test")
    assert len(rows) == 1  # 记忆已落盘, 不依赖时序巧合


@pytest.mark.asyncio
async def test_merged_burst_is_remembered_in_full(tmp_path: Path) -> None:
    """合并回合写入记忆的是**整个 burst**, 而非只有触发那条 (记忆保真度)。"""
    from isac.memory.embedder import EmbeddingManager
    from isac.memory.pipeline import MemoryRetrievalPipeline
    from isac.memory.storage.graph import GraphStore
    from isac.memory.storage.metadata import MetadataStore
    from isac.memory.storage.sparse import SparseBM25Index
    from isac.memory.storage.vector import VectorStore

    metadata_store = MetadataStore(str(tmp_path / "metadata.db"))
    await metadata_store.init_schema()
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    provider_manager.register(SlowFakeProvider(scripted_replies=[make_final_reply("知道了")]))
    session_mgr = SessionManager({})
    session_lock = SessionLockManager()
    channel_registry = ChannelRegistry()
    channel = FakeChannel()
    channel_registry.register(channel)
    services: dict[str, Any] = {
        "global_config": {
            "conversation": {"enabled": True, "debounce_seconds": 0.2},
            "control": {"agents_dir": str(tmp_path / "agents")},
        },
        "provider_manager": provider_manager,
        "memory_factory": lambda ns: MemoryRetrievalPipeline(
            namespace=ns, metadata=metadata_store,
            vector=VectorStore(str(tmp_path / f"v-{ns}.db")), sparse=SparseBM25Index(),
            graph=GraphStore(str(tmp_path / "g.db")), embedder=EmbeddingManager({}), reranker=None,
        ),
        "metrics": metrics,
        "session_mgr": session_mgr,
        "session_lock": session_lock,
        "channel_registry": channel_registry,
    }
    am = AgentManager(services)
    await am.create(AgentConfig(agent_id="a", display_name="A"))
    await am.start("a")
    router = MessageRouter(
        RoutingRules(default_agents={"fake": "a"}), agents_provider=am.routing_infos
    )
    handle_message, drain = make_message_dispatcher(
        event_bus=EventBus(), router=router, session_mgr=session_mgr, user_mapper=UserMapper(),
        agent_manager=am, channel_registry=channel_registry, metrics=metrics,
        session_lock=session_lock, drain_timeout_seconds=15.0,
    )
    channel.on_message = handle_message

    await _inject(channel, "burst_alpha_one")
    await asyncio.sleep(0.02)
    await _inject(channel, "burst_beta_two")
    await _drain_all(am, drain)

    # 突发里靠前的那条也必须能被检索到 (此前只存了触发合并的那条)
    assert await metadata_store.search_fts("a", "burst_alpha_one")
    assert await metadata_store.search_fts("a", "burst_beta_two")


# ── high(security): memory_query 空 scopes 必须拒绝 ───────────


@pytest.mark.asyncio
async def test_memory_query_empty_scopes_denied(tmp_path: Path) -> None:
    """Link 授予 memory_query 但未配 visible_memory_scopes 时拒绝 (此前泄露全部记忆)。"""
    from isac.memory.embedder import EmbeddingManager
    from isac.memory.pipeline import MemoryRetrievalPipeline
    from isac.memory.storage.graph import GraphStore
    from isac.memory.storage.metadata import MetadataStore
    from isac.memory.storage.sparse import SparseBM25Index
    from isac.memory.storage.vector import VectorStore

    metadata_store = MetadataStore(str(tmp_path / "metadata.db"))
    await metadata_store.init_schema()
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    provider_manager.register(FakeLLMProvider())
    sparse = SparseBM25Index()
    services: dict[str, Any] = {
        "global_config": {},
        "provider_manager": provider_manager,
        "memory_factory": lambda ns: MemoryRetrievalPipeline(
            namespace=ns, metadata=metadata_store,
            vector=VectorStore(str(tmp_path / f"v-{ns}.db")), sparse=sparse,
            graph=GraphStore(str(tmp_path / "g.db")), embedder=EmbeddingManager({}), reranker=None,
        ),
        "metrics": metrics,
    }
    am = AgentManager(services)
    await am.create(AgentConfig(agent_id="b", display_name="B"))
    await am.start("b")
    await metadata_store.store_episode(
        "b", {"content": "u9: private_secret_alpha 别告诉别人", "session_id": "s", "user_id": "u9"}
    )
    instance = await am.get("b")
    await instance.memory.warm_up_sparse_index()

    # 空 scopes: 必须拒绝 (deny-by-default), 不能返回任何内容
    empty = InterAgentMessage(
        from_agent="a", to_agent="b", type="memory_query",
        content="private_secret_alpha", context={"filters": {"scopes": []}},
    )
    assert await _answer_memory_query(am, "b", empty) == ""

    # 显式授予 user:u9 时才可见
    scoped = InterAgentMessage(
        from_agent="a", to_agent="b", type="memory_query",
        content="private_secret_alpha", context={"filters": {"scopes": ["user:u9"]}},
    )
    assert "private_secret_alpha" in await _answer_memory_query(am, "b", scoped)


# ── medium: handoff TTL + 撤销 ────────────────────────────────


def test_handoff_expires_and_can_be_revoked() -> None:
    """handoff 带 TTL 到期回落, 且可显式撤销 (此前永久劫持全部路由信号)。"""
    router = MessageRouter(RoutingRules(default_agents={"fake": "a"}), agents_provider=lambda: [])

    router.set_handoff("fake", None, "u1", "b", ttl_seconds=0.05)
    assert router.get_handoff("fake", None, "u1") == "b"
    import time as _t

    _t.sleep(0.06)
    assert router.get_handoff("fake", None, "u1") is None  # 到期自动回落

    router.set_handoff("fake", None, "u1", "b")
    router.clear_handoff("fake", None, "u1")
    assert router.get_handoff("fake", None, "u1") is None  # 显式撤销


@pytest.mark.asyncio
async def test_handoff_to_self_revokes_ownership() -> None:
    """接手方把会话移交回自己 = 交还归属 (给用户/Agent 一条退出路径)。"""
    from isac.agent.tools.social.handoff_conversation import HandoffConversationTool
    from isac.core.types import AgentContext
    from isac.gateway.models import Session
    from isac.runtime.mesh.actions import MeshActionBroker

    bus = InterAgentBus()
    bus.add_link(InterAgentLink(from_agent="b", to_agent="b", permissions=["handoff"]))

    async def _deliver(_a: str, _m: InterAgentMessage) -> str:
        return "ok"

    bus.set_deliver(_deliver)
    router = MessageRouter(RoutingRules(), agents_provider=lambda: [])
    router.set_handoff("fake", None, "u1", "b")

    tool = HandoffConversationTool()
    ctx = type("Ctx", (), {})()
    ctx.args = {"target_agent": "b", "summary": "交还"}
    ctx.services = {"mesh_action_broker": MeshActionBroker(bus), "agent_id": "b", "router": router}
    ctx.agent_context = AgentContext(
        session=Session(session_id="s1", user_id="u1", agent_id="b", platform="fake"),
        user_profile=None, current_message=None,
    )
    result = await tool.execute(ctx)
    assert result.is_error is False
    assert router.get_handoff("fake", None, "u1") is None


@pytest.mark.asyncio
async def test_handoff_to_non_running_target_rejected() -> None:
    """Fix-70: 目标 Agent 不可路由时拒绝移交 —— 不发摘要、不登记 handoff
    (此前移交给死 Agent 会劫持会话路由直到 TTL 到期)。"""
    from isac.agent.tools.social.handoff_conversation import HandoffConversationTool
    from isac.core.types import AgentContext
    from isac.gateway.models import Session
    from isac.runtime.mesh.actions import MeshActionBroker

    bus = InterAgentBus()
    bus.add_link(InterAgentLink(from_agent="a", to_agent="ghost", permissions=["handoff"]))
    delivered: list[str] = []

    async def _deliver(agent: str, _m: InterAgentMessage) -> str:
        delivered.append(agent)
        return "ok"

    bus.set_deliver(_deliver)
    router = MessageRouter(RoutingRules(), agents_provider=lambda: [])  # ghost 不可路由
    tool = HandoffConversationTool()
    ctx = type("Ctx", (), {})()
    ctx.args = {"target_agent": "ghost", "summary": "请接手"}
    ctx.services = {"mesh_action_broker": MeshActionBroker(bus), "agent_id": "a", "router": router}
    ctx.agent_context = AgentContext(
        session=Session(session_id="s1", user_id="u1", agent_id="a", platform="fake"),
        user_profile=None, current_message=None,
    )
    result = await tool.execute(ctx)
    assert result.is_error is True
    assert "未运行" in result.content
    assert delivered == []  # 摘要未投递
    assert router.get_handoff("fake", None, "u1") is None  # 未登记 handoff


# ── medium: UserMapper 并发首次接触不产生身份分裂 ─────────────


@pytest.mark.asyncio
async def test_user_mapper_concurrent_first_contact_single_identity(tmp_path: Path) -> None:
    """同一用户在多个会话并发首次出现时只创建一个 master_id (此前 TOCTOU 身份分裂)。"""
    mapper = UserMapper(str(tmp_path / "identity.db"))
    profiles = await asyncio.gather(*[mapper.resolve("qq", "10001") for _ in range(8)])
    assert len({p.user_id for p in profiles}) == 1


# ── medium: 互联消息豁免 debounce ─────────────────────────────


@pytest.mark.asyncio
async def test_interagent_message_not_delayed_by_debounce() -> None:
    """A2A 消息不被 debounce 静默窗口延迟/弃权 (已过 Link ACL 的显式协作动作)。"""
    from isac.core.constants import INTERAGENT_PLATFORM
    from isac.gateway.models import Session

    provider = SlowFakeProvider(scripted_replies=[make_final_reply("已处理通知")])
    am, _channel, _drain = await _build_env(provider, conversation={"debounce_seconds": 5.0})

    msg = ISACMessage(
        msg_id="", platform=INTERAGENT_PLATFORM, timestamp=0, user_id="peer",
        user_name="", group_id=None, content="[通知] 用户提到你",
    )
    session = Session(session_id="s-inter", user_id="peer", agent_id="a", platform=INTERAGENT_PLATFORM)
    reply = await asyncio.wait_for(am.handle_message("a", msg, session, None), timeout=2.0)
    assert reply == "已处理通知"  # 没被 5 秒静默窗口拖住, 也没被弃权


# ── low: 会话快照过期清理 ─────────────────────────────────────


def test_expired_snapshots_are_cleaned_on_load_all(tmp_path: Path) -> None:
    """load_all 顺带删除过期/损坏快照 (此前目录只增不减, 每次组装全量重扫)。"""
    import json
    import time as _t

    from isac.runtime.conversation import ConversationStateStore

    directory = tmp_path / "a" / "conversation"
    directory.mkdir(parents=True)
    (directory / "fresh.json").write_text(
        json.dumps({"agent_id": "a", "session_id": "fake:user:fresh", "last_active_at": _t.time()}),
        encoding="utf-8",
    )
    (directory / "stale.json").write_text(
        json.dumps(
            {"agent_id": "a", "session_id": "fake:user:stale", "last_active_at": _t.time() - 90000}
        ),
        encoding="utf-8",
    )
    (directory / "broken.json").write_text("{not json", encoding="utf-8")

    snapshots = ConversationStateStore(base_dir=str(tmp_path)).load_all("a")

    assert set(snapshots) == {"fake:user:fresh"}
    assert (directory / "fresh.json").exists()
    assert not (directory / "stale.json").exists()  # 过期已清理
    assert not (directory / "broken.json").exists()  # 损坏已清理


# ── low: InterAgentMessage.trace_id 契约 ──────────────────────


@pytest.mark.asyncio
async def test_interagent_message_carries_trace_id() -> None:
    """A2A 消息带 trace_id 并从日志上下文继承, 响应沿用同一 trace (SPEC 2.10)。"""
    from isac.utils.logging_context import bind_log_context

    bus = InterAgentBus()
    bus.add_link(InterAgentLink(from_agent="a", to_agent="b"))
    seen: list[InterAgentMessage] = []

    async def _deliver(_agent_id: str, msg: InterAgentMessage) -> str:
        seen.append(msg)
        return "ok"

    bus.set_deliver(_deliver)
    with bind_log_context(trace_id="trace-abc"):
        response = await bus.send(
            InterAgentMessage(from_agent="a", to_agent="b", type="request", content="hi")
        )
    assert seen[0].trace_id == "trace-abc"  # 从日志上下文继承
    assert response is not None and response.trace_id == "trace-abc"  # 响应沿用同一 trace
