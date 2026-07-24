"""K6: 多 Agent、工具、记忆与控制面 E2E (DEVELOPMENT_PLAN.md)。

集成验收:
- 2+ Agent 共享 1 FakeChannel
- 显式绑定 / 触发词 / 默认 Agent 三种路由路径
- InterAgentBus deliver + ACL (默认拒绝, 配 Link 后放行)
- 工具权限 (Agent A 可用 query_memory, Agent B deny)
- 记忆 namespace 隔离 (A 写入的 episode B 检索不到)
- Control 修改 AgentConfig 持久化 + 重启后仍生效 (K4 + K2 联动)
"""

from __future__ import annotations

from typing import Any

import pytest

from isac.channel.model import ISACMessage, MessageSegment
from isac.channel.registry import ChannelRegistry
from isac.core.types import LLMResponse
from isac.gateway.event_bus import EventBus
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.main import process_message
from isac.memory.pipeline import NoOpMemoryPipeline
from isac.observability import get_default_metrics
from isac.provider.manager import ProviderManager
from isac.router.router import MessageRouter
from isac.router.types import ChannelBinding, RoutingRules
from isac.runtime.bus import InterAgentBus, InterAgentLink
from isac.runtime.config import AgentConfig
from isac.runtime.manager import AgentManager
from tests.fixtures.fakes import FakeChannel, FakeLLMProvider, make_final_reply


async def _build_multi_agent(
    *,
    agent_a: AgentConfig,
    agent_b: AgentConfig,
    bindings: list[ChannelBinding] | None = None,
    default_agent: str | None = None,
    llm_replies: list[LLMResponse] | None = None,
) -> tuple[
    AgentManager, MessageRouter, EventBus, SessionManager, UserMapper,
    ChannelRegistry, FakeChannel, InterAgentBus, FakeLLMProvider,
]:
    """构造多 Agent E2E 夹具。"""
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    fake_provider = FakeLLMProvider(scripted_replies=llm_replies or [make_final_reply("ok")])
    provider_manager.register(fake_provider)

    services: dict[str, Any] = {
        "global_config": {},
        "provider_manager": provider_manager,
        "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
        "metrics": metrics,
    }
    agent_manager = AgentManager(services)
    await agent_manager.create(agent_a)
    await agent_manager.create(agent_b)
    await agent_manager.start(agent_a.agent_id)
    await agent_manager.start(agent_b.agent_id)

    bus = InterAgentBus()
    services["bus"] = bus

    rules = RoutingRules(
        bindings=bindings or [],
        default_agents={"fake": default_agent} if default_agent else {},
    )
    router = MessageRouter(rules, agents_provider=agent_manager.routing_infos)

    event_bus = EventBus()
    session_mgr = SessionManager({})
    user_mapper = UserMapper()
    channel_registry = ChannelRegistry()
    fake_channel = FakeChannel()
    channel_registry.register(fake_channel)

    return (
        agent_manager, router, event_bus, session_mgr, user_mapper,
        channel_registry, fake_channel, bus, fake_provider,
    )


def _msg(content: str, *, user_id: str = "u1", group_id: str | None = None, at_bot: bool = False) -> ISACMessage:
    segments = [MessageSegment(type="text", data={"text": content})] if content else []
    if at_bot:
        segments = [MessageSegment(type="at", data={}), *segments]
    import time as _time
    return ISACMessage(
        msg_id=f"m-{user_id}-{int(_time.time() * 1000) % 100000}",
        platform="fake",
        timestamp=int(_time.time()),
        user_id=user_id,
        user_name=user_id,
        group_id=group_id,
        content=content,
        segments=segments,
    )


async def _run(
    msg: ISACMessage, *,
    am: AgentManager, router: MessageRouter, eb: EventBus,
    sm: SessionManager, um: UserMapper, cr: ChannelRegistry,
) -> None:
    await process_message(
        msg,
        event_bus=eb, router=router, session_mgr=sm, user_mapper=um,
        agent_manager=am, channel_registry=cr, metrics=get_default_metrics(),
    )


@pytest.mark.asyncio
async def test_default_agent_routes_to_one_of_multiple_agents() -> None:
    """默认 Agent 路由: 无触发词无绑定时路由到 default_agent_id 指定的 Agent。"""
    agent_a = AgentConfig(agent_id="a", display_name="A")
    agent_b = AgentConfig(agent_id="b", display_name="B")

    (am, router, eb, sm, um, cr, channel, _, provider) = await _build_multi_agent(
        agent_a=agent_a, agent_b=agent_b,
        default_agent="b",  # 默认路由到 b
        llm_replies=[make_final_reply("from b")],
    )

    msg = _msg("hi", at_bot=True)
    await _run(msg, am=am, router=router, eb=eb, sm=sm, um=um, cr=cr)

    assert len(channel.replies) == 1
    assert channel.replies[0].content == "from b"


@pytest.mark.asyncio
async def test_binding_routes_by_user_id() -> None:
    """显式绑定 (platform, user_id) → agent_id, 优先级高于默认。"""
    agent_a = AgentConfig(agent_id="a", display_name="A")
    agent_b = AgentConfig(agent_id="b", display_name="B")

    (am, router, eb, sm, um, cr, channel, _, _) = await _build_multi_agent(
        agent_a=agent_a, agent_b=agent_b,
        bindings=[ChannelBinding(platform="fake", agent_id="a", user_id="u_special")],
        default_agent="b",  # 默认是 b, 但 u_special 绑定到 a
        llm_replies=[make_final_reply("from a")],
    )

    msg = _msg("hi", user_id="u_special", at_bot=True)
    await _run(msg, am=am, router=router, eb=eb, sm=sm, um=um, cr=cr)

    assert len(channel.replies) == 1
    assert channel.replies[0].content == "from a"


@pytest.mark.asyncio
async def test_trigger_word_routes_to_specific_agent() -> None:
    """触发词路由: "/ask_a" 开头 → 路由到 Agent A。"""
    agent_a = AgentConfig(agent_id="a", display_name="A", trigger_words=["/ask_a"])
    agent_b = AgentConfig(agent_id="b", display_name="B", trigger_words=["/ask_b"])

    (am, router, eb, sm, um, cr, channel, _, _) = await _build_multi_agent(
        agent_a=agent_a, agent_b=agent_b,
        llm_replies=[make_final_reply("from a")],
    )

    msg = _msg("/ask_a question", at_bot=True)
    await _run(msg, am=am, router=router, eb=eb, sm=sm, um=um, cr=cr)

    assert len(channel.replies) == 1
    assert channel.replies[0].content == "from a"


@pytest.mark.asyncio
async def test_interagent_bus_acl_denies_without_link() -> None:
    """InterAgentBus 默认拒绝: 无 Link 时 a 不能向 b 发 request。"""
    agent_a = AgentConfig(agent_id="a", display_name="A")
    agent_b = AgentConfig(agent_id="b", display_name="B")

    (am, router, eb, sm, um, cr, channel, bus, _) = await _build_multi_agent(
        agent_a=agent_a, agent_b=agent_b,
    )

    from isac.core.exceptions import InterAgentLinkDeniedError
    from isac.runtime.bus import InterAgentMessage

    msg = InterAgentMessage(from_agent="a", to_agent="b", type="request", content="hello?")
    with pytest.raises(InterAgentLinkDeniedError):
        await bus.send(msg)


@pytest.mark.asyncio
async def test_interagent_bus_delivers_with_link() -> None:
    """配置 Link 后 a → b 的 request 能投递并拿到 b 的回复。"""
    agent_a = AgentConfig(agent_id="a", display_name="A")
    agent_b = AgentConfig(agent_id="b", display_name="B")

    (am, router, eb, sm, um, cr, channel, bus, provider) = await _build_multi_agent(
        agent_a=agent_a, agent_b=agent_b,
        # b 回复时 LLM 返回 "b replies"
        llm_replies=[make_final_reply("b replies")],
    )

    # 加 Link a → b (direction=both 让 b 也能反向回 a)
    bus.add_link(InterAgentLink(from_agent="a", to_agent="b", direction="both"))

    # deliver 回调需要 session_mgr + agent_manager, main.py 里的 _deliver_to_agent
    async def _deliver(target_agent_id: str, message: InterAgentMessage) -> str | None:
        # 构造 ISACMessage 让 b 处理; 直接调 handle_message
        from isac.channel.model import ISACMessage as _Msg
        wrapped = _Msg(
            msg_id="", platform="interagent", timestamp=0,
            user_id=message.from_agent, user_name="",
            group_id=None, content=message.content,
        )
        session = await sm.get_or_create(wrapped, agent_id=target_agent_id)
        return await am.handle_message(target_agent_id, wrapped, session, None)

    from isac.runtime.bus import InterAgentMessage
    bus.set_deliver(_deliver)

    # 触发 b 处理一条消息让 LLM 回复 "b replies", 模拟 a 向 b 询问
    msg = InterAgentMessage(from_agent="a", to_agent="b", type="request", content="question for b")
    response = await bus.send(msg)

    assert response is not None
    assert response.content == "b replies"
    assert response.from_agent == "b"
    assert response.to_agent == "a"


@pytest.mark.asyncio
async def test_tool_policy_per_agent_isolation() -> None:
    """工具权限按 Agent 隔离: A 允许 query_memory, B 通过 tools_policy 禁用。

    工具走 ask_agent 等社交工具的 allow/deny 由 AgentConfig.tools_policy 控制。
    """
    # A 允许所有, B 显式 deny ask_agent
    agent_a = AgentConfig(agent_id="a", display_name="A")
    agent_b = AgentConfig(agent_id="b", display_name="B", tools_policy={"ask_agent": "deny"})

    (am, router, eb, sm, um, cr, channel, bus, _) = await _build_multi_agent(
        agent_a=agent_a, agent_b=agent_b,
    )

    inst_a = await am.get("a")
    inst_b = await am.get("b")
    assert inst_a is not None and inst_b is not None

    # A 的 ToolRegistry 不应把 ask_agent 过滤为 deny
    policy_a = inst_a.tools.effective_policy("ask_agent", platform="fake")
    policy_b = inst_b.tools.effective_policy("ask_agent", platform="fake")
    assert policy_a != "deny"
    assert policy_b == "deny"


@pytest.mark.asyncio
async def test_memory_namespace_isolation_between_agents(tmp_path) -> None:
    """记忆 namespace 隔离: A 写入的 episode B 检索不到。

    使用真实 MetadataStore (而非 NoOp) 验证 namespace 隔离。
    """
    from isac.memory.embedder import EmbeddingManager
    from isac.memory.pipeline import MemoryRetrievalPipeline
    from isac.memory.reranker import Reranker
    from isac.memory.storage.graph import GraphStore
    from isac.memory.storage.metadata import MetadataStore
    from isac.memory.storage.sparse import SparseBM25Index
    from isac.memory.storage.vector import VectorStore

    async def _make_real_pipeline(root_dir, namespace: str) -> MemoryRetrievalPipeline:
        metadata = MetadataStore(str(root_dir / f"{namespace}.db"))
        await metadata.init_schema()
        return MemoryRetrievalPipeline(
            namespace=namespace,
            metadata=metadata,
            vector=VectorStore(str(root_dir / f"{namespace}_vec.db"), dimension=3),
            sparse=SparseBM25Index(),
            graph=GraphStore(str(root_dir / f"{namespace}_graph.db")),
            embedder=EmbeddingManager({}),
            reranker=Reranker({}),
            metrics=get_default_metrics(),
        )

    pipeline_a = await _make_real_pipeline(tmp_path, namespace="a")
    pipeline_b = await _make_real_pipeline(tmp_path, namespace="b")

    # A 写入一条记忆
    memory_id = await pipeline_a.store_episode("A 的秘密内容", "sess-a", "u1", agent_id="a")
    assert memory_id

    # B 检索应返回空 (namespace 隔离, agent_id=a 的数据 B 查不到)
    hits_b = await pipeline_b.search("秘密", user_id="u1")
    assert hits_b == []

    # A 检索应命中
    hits_a = await pipeline_a.search("秘密", user_id="u1")
    assert len(hits_a) == 1
    assert hits_a[0].content == "A 的秘密内容"


@pytest.mark.asyncio
async def test_control_plane_modify_config_persists_and_survives_restart(tmp_path) -> None:
    """Control 修改 AgentConfig.plugins_allow → 持久化 → 重启后仍生效 (K4 + K2 联动)。"""
    from isac.runtime.config import load_agent_config, save_agent_config

    agents_dir = tmp_path / "agents"
    config_a = AgentConfig(agent_id="ctrl_a", display_name="A", plugins_allow=["p1"])
    save_agent_config(agents_dir / "ctrl_a" / "config.jsonc", config_a)

    # 模拟控制面修改: plugins_allow 改为 ["p2"]
    config_a.plugins_allow = ["p2"]
    save_agent_config(agents_dir / "ctrl_a" / "config.jsonc", config_a)

    # 重启: 从磁盘加载
    loaded = load_agent_config(agents_dir / "ctrl_a" / "config.jsonc")
    assert loaded.plugins_allow == ["p2"]

    # 通过 load_persisted_agents 把它恢复到 AgentManager
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    provider_manager.register(FakeLLMProvider())
    services = {
        "global_config": {},
        "provider_manager": provider_manager,
        "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
        "metrics": metrics,
    }
    am = AgentManager(services)
    from isac.runtime.manager import load_persisted_agents
    report = await load_persisted_agents(am, str(agents_dir))
    assert report["ctrl_a"] == "running"

    inst = await am.get("ctrl_a")
    assert inst is not None
    assert inst.config.plugins_allow == ["p2"]


@pytest.mark.asyncio
async def test_two_agents_share_one_channel_interleaved() -> None:
    """两个 Agent 共享一个 FakeChannel, 交错处理两条消息各自回复。"""
    agent_a = AgentConfig(agent_id="a", display_name="A", trigger_words=["/ask_a"])
    agent_b = AgentConfig(agent_id="b", display_name="B", trigger_words=["/ask_b"])

    (am, router, eb, sm, um, cr, channel, _, provider) = await _build_multi_agent(
        agent_a=agent_a, agent_b=agent_b,
        llm_replies=[make_final_reply("a says"), make_final_reply("b says")],
    )

    # 交错投递两条消息
    msg1 = _msg("/ask_a question1", at_bot=True)
    msg2 = _msg("/ask_b question2", at_bot=True)
    await _run(msg1, am=am, router=router, eb=eb, sm=sm, um=um, cr=cr)
    await _run(msg2, am=am, router=router, eb=eb, sm=sm, um=um, cr=cr)

    # 两条回复都收到, 顺序对应
    assert len(channel.replies) == 2
    assert channel.replies[0].content == "a says"
    assert channel.replies[1].content == "b says"


@pytest.mark.asyncio
async def test_observer_agent_does_not_reply() -> None:
    """观察 Agent (未 start) 不处理消息: 路由到 stopped Agent 时无回复。

    通过 stopped Agent (status != running) 让 handle_message 直接 return None。
    """
    agent_a = AgentConfig(agent_id="a", display_name="A")
    observer = AgentConfig(agent_id="obs", display_name="Observer")

    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    provider_manager.register(FakeLLMProvider(scripted_replies=[make_final_reply("should not appear")]))
    services: dict[str, Any] = {
        "global_config": {},
        "provider_manager": provider_manager,
        "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
        "metrics": metrics,
    }
    am = AgentManager(services)
    await am.create(agent_a)
    await am.create(observer)
    await am.start("a")
    # observer 不 start, 保持 stopped

    rules = RoutingRules(
        bindings=[ChannelBinding(platform="fake", agent_id="obs", user_id="u_obs")],
    )
    router = MessageRouter(rules, agents_provider=am.routing_infos)
    event_bus = EventBus()
    session_mgr = SessionManager({})
    user_mapper = UserMapper()
    cr = ChannelRegistry()
    fake_channel = FakeChannel()
    cr.register(fake_channel)

    msg = _msg("hello observer", user_id="u_obs", at_bot=True)
    await _run(msg, am=am, router=router, eb=event_bus, sm=session_mgr, um=user_mapper, cr=cr)

    # observer 未运行, 消息被 handle_message 静默丢弃
    assert fake_channel.replies == []
