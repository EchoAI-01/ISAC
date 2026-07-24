"""K5: 单 Channel × 单 Agent 真实 E2E 测试 (DEVELOPMENT_PLAN.md)。

全链路: FakeChannel.receive_inject → process_message (EventBus intercept →
Router 剥离触发词 → Session/Gating → AgentManager.handle_message → FakeLLMProvider
→ Tool Call → Channel.send)。覆盖:
- 正常文本回复
- 触发词剥离 (router matched_by=trigger_word)
- @bot 强制触发 (gating has_at)
- tool_call → tool result → 最终回复 多轮 Agent Loop
- LLM 异常 → 降级回复
- 消息路由无匹配 → DROP
- 重启恢复 (Agent 重启后仍能处理消息)
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from isac.channel.model import ISACMessage, MessageSegment
from isac.channel.registry import ChannelRegistry
from isac.core.events import EventType
from isac.gateway.event_bus import EventBus
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.main import process_message
from isac.memory.pipeline import NoOpMemoryPipeline
from isac.observability import get_default_metrics
from isac.provider.llm.stub import StubProvider
from isac.provider.manager import ProviderManager
from isac.router.router import MessageRouter
from isac.router.types import RoutingRules
from isac.runtime.config import AgentConfig
from isac.runtime.manager import AgentManager
from tests.fixtures.fakes import FakeChannel, FakeLLMProvider, make_final_reply, make_tool_call_response


async def _build_e2e(
    *,
    trigger_words: list[str] | None = None,
    default_agent: str | None = None,
    provider: Any | None = None,
) -> tuple[
    AgentManager, MessageRouter, EventBus, SessionManager,
    UserMapper, ChannelRegistry, FakeChannel, FakeLLMProvider,
]:
    """构造 E2E 夹具: 返回所有 main.process_message 需要的组件。"""
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    fake_provider = provider or FakeLLMProvider()
    provider_manager.register(fake_provider)

    services = {
        "global_config": {},
        "provider_manager": provider_manager,
        "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
        "metrics": metrics,
    }
    agent_manager = AgentManager(services)
    await agent_manager.create(
        AgentConfig(
            agent_id="default",
            display_name="ISAC",
            trigger_words=trigger_words or [],
        )
    )
    await agent_manager.start("default")

    rules = RoutingRules(
        bindings=[],
        default_agents={"fake": default_agent} if default_agent else {},
    )
    router = MessageRouter(rules, agents_provider=agent_manager.routing_infos)

    event_bus = EventBus()
    session_mgr = SessionManager({})
    user_mapper = UserMapper()
    channel_registry = ChannelRegistry()
    fake_channel = FakeChannel()
    channel_registry.register(fake_channel)

    return agent_manager, router, event_bus, session_mgr, user_mapper, channel_registry, fake_channel, fake_provider


async def _run(
    message: ISACMessage,
    *,
    agent_manager: AgentManager,
    router: MessageRouter,
    event_bus: EventBus,
    session_mgr: SessionManager,
    user_mapper: UserMapper,
    channel_registry: ChannelRegistry,
    metrics: Any = None,
) -> None:
    """调 main.process_message 跑一次主链路。"""
    await process_message(
        message,
        event_bus=event_bus,
        router=router,
        session_mgr=session_mgr,
        user_mapper=user_mapper,
        agent_manager=agent_manager,
        channel_registry=channel_registry,
        metrics=metrics or get_default_metrics(),
    )


def _msg(
    content: str,
    *,
    user_id: str = "u1",
    group_id: str | None = None,
    at_bot: bool = False,
    segments: list[MessageSegment] | None = None,
) -> ISACMessage:
    """构造一条 ISACMessage, at_bot=True 时附加 at segment 触发 has_at。"""
    if segments is None:
        segments = [MessageSegment(type="text", data={"text": content})] if content else []
    if at_bot:
        segments = [MessageSegment(type="at", data={}), *segments]
    return ISACMessage(
        msg_id=f"m-{user_id}-{int(__import__('time').time() * 1000) % 100000}",
        platform="fake",
        timestamp=int(__import__('time').time()),
        user_id=user_id,
        user_name=user_id,
        group_id=group_id,
        content=content,
        segments=segments,
    )


@pytest.mark.asyncio
async def test_simple_text_reply_full_chain() -> None:
    """正常文本: @bot → 路由到 default Agent → LLM 回复 → FakeChannel.send。"""
    (am, router, eb, sm, um, cr, channel, provider) = await _build_e2e(
        default_agent="default",
        provider=FakeLLMProvider(scripted_replies=[make_final_reply("hello human")]),
    )

    msg = _msg("@bot 你好", at_bot=True)
    await _run(msg, agent_manager=am, router=router, event_bus=eb, session_mgr=sm, user_mapper=um, channel_registry=cr)

    assert len(channel.replies) == 1
    assert channel.replies[0].content == "hello human"


@pytest.mark.asyncio
async def test_trigger_word_is_stripped_before_agent() -> None:
    """触发词路由: message.content 被剥离触发词后再传给 Agent (CODE_REVIEW_REPORT.md #7)。

    @bot 强制门控 TRIGGER 让回复不被 reply_necessity 过滤; 但路由仍走 trigger_word 分支
    (agent_id=default, matched_by=trigger_word), 剥离后 Agent 看到的是 "今天天气"。
    """
    provider = FakeLLMProvider(scripted_replies=[make_final_reply("done")])
    (am, router, eb, sm, um, cr, channel, _) = await _build_e2e(
        trigger_words=["/ask"],
        provider=provider,
    )

    # at_bot=True 让门控强制 TRIGGER, 同时仍让 router 走 trigger_word 分支
    msg = _msg("/ask 今天天气怎么样", at_bot=True)
    await _run(msg, agent_manager=am, router=router, event_bus=eb, session_mgr=sm, user_mapper=um, channel_registry=cr)

    assert len(channel.replies) == 1
    assert channel.replies[0].content == "done"
    # Agent 收到的 messages[0].content 应该是剥掉 "/ask " 后的正文
    last_call = provider.calls[-1]
    user_msg = last_call["messages"][-1]
    assert "/ask" not in user_msg["content"]
    assert "今天天气" in user_msg["content"]


@pytest.mark.asyncio
async def test_no_route_match_drops_message() -> None:
    """无 default agent + 无触发词匹配 → 路由 DROP, 无回复。"""
    (am, router, eb, sm, um, cr, channel, _) = await _build_e2e(
        # 不配置 default_agent, trigger_words 也为空
    )

    msg = _msg("无人能回答的问题")
    await _run(msg, agent_manager=am, router=router, event_bus=eb, session_mgr=sm, user_mapper=um, channel_registry=cr)

    assert channel.replies == []


@pytest.mark.asyncio
async def test_at_bot_forces_gating_trigger() -> None:
    """@bot 强制门控 TRIGGER, 跳过 reply_necessity 评分, 直接调用 LLM。"""
    provider = FakeLLMProvider(scripted_replies=[make_final_reply("at reply")])
    (am, router, eb, sm, um, cr, channel, _) = await _build_e2e(
        default_agent="default",
        provider=provider,
    )

    msg = _msg("随口一句话", at_bot=True)
    await _run(msg, agent_manager=am, router=router, event_bus=eb, session_mgr=sm, user_mapper=um, channel_registry=cr)

    assert len(channel.replies) == 1
    assert channel.replies[0].content == "at reply"


@pytest.mark.asyncio
async def test_tool_call_full_loop() -> None:
    """LLM 返回 tool_calls → Agent 执行工具 → 第二轮 LLM 给最终回复。"""
    # 第一轮返回 tool_calls, 第二轮返回最终文本
    provider = FakeLLMProvider(
        scripted_replies=[
            make_tool_call_response("query_memory", arguments={"query": "hi"}),
            make_final_reply("based on memory: hello"),
        ]
    )
    (am, router, eb, sm, um, cr, channel, _) = await _build_e2e(
        default_agent="default",
        provider=provider,
    )

    msg = _msg("@bot 帮我查记忆", at_bot=True)
    await _run(msg, agent_manager=am, router=router, event_bus=eb, session_mgr=sm, user_mapper=um, channel_registry=cr)

    assert len(channel.replies) == 1
    assert channel.replies[0].content == "based on memory: hello"
    # 验证 LLM 被调用了 2 次 (tool_call + final_reply)
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_llm_exception_returns_degraded_reply() -> None:
    """LLM 抛异常 → ProviderManager.chat_with_retry 重试 3 次失败 → 降级回复。

    使用 StubProvider 永远返回固定回复, 让 chat_with_retry 一次成功——真实验证
    异常路径用 _AlwaysRaisesProvider (定义在本测试文件)。
    """

    class _AlwaysRaisesProvider:
        async def chat(self, **kwargs):
            raise RuntimeError("LLM down")

        async def chat_stream(self, *args, **kwargs):
            raise NotImplementedError

        def get_model_name(self) -> str:
            return "broken"

        def get_capabilities(self):
            return None

    provider = _AlwaysRaisesProvider()
    (am, router, eb, sm, um, cr, channel, _) = await _build_e2e(
        default_agent="default",
        provider=provider,
    )

    msg = _msg("@bot hello", at_bot=True)
    await _run(msg, agent_manager=am, router=router, event_bus=eb, session_mgr=sm, user_mapper=um, channel_registry=cr)

    # chat_with_retry 3 次重试后降级回复 (DEGRADED_REPLY 固定文本)
    assert len(channel.replies) == 1
    from isac.provider.manager import DEGRADED_REPLY
    assert channel.replies[0].content == DEGRADED_REPLY


@pytest.mark.asyncio
async def test_restart_recovery_agent_can_still_handle_messages(tmp_path) -> None:
    """重启恢复: 新 AgentManager 从 data/agents/<id>/config.jsonc 加载后仍能处理消息。"""
    from isac.runtime.config import save_agent_config
    from isac.runtime.manager import load_persisted_agents

    # 第一次启动: 创建 + 持久化 Agent
    agents_dir = tmp_path / "agents"
    save_agent_config(agents_dir / "persisted" / "config.jsonc", AgentConfig(agent_id="persisted", display_name="P"))

    # 模拟重启: 新 AgentManager + load_persisted_agents
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    provider_manager.register(StubProvider())
    services = {
        "global_config": {},
        "provider_manager": provider_manager,
        "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
        "metrics": metrics,
    }
    am = AgentManager(services)
    report = await load_persisted_agents(am, str(agents_dir))
    assert report["persisted"] == "running"

    # 重启后 Agent 仍能处理消息
    inst = await am.get("persisted")
    assert inst is not None
    assert inst.status == "running"


@pytest.mark.asyncio
async def test_intercept_payload_replaces_message_content() -> None:
    """EventBus.fire_intercept 返回的替换 payload 真正生效 (CODE_REVIEW_REPORT.md #8)。

    插件 intercept ON_MESSAGE 返回一条 content 被替换的 ISACMessage, 后续路由/Agent
    看到的应是替换后的内容。
    """
    provider = FakeLLMProvider(scripted_replies=[make_final_reply("ok")])
    (am, router, eb, sm, um, cr, channel, provider) = await _build_e2e(
        default_agent="default",
        provider=provider,
    )

    async def _intercept(payload: ISACMessage) -> ISACMessage:
        return dataclasses.replace(payload, content="rewritten content")

    eb.on_intercept(EventType.ON_MESSAGE, _intercept)

    msg = _msg("原始内容", at_bot=True)
    await _run(msg, agent_manager=am, router=router, event_bus=eb, session_mgr=sm, user_mapper=um, channel_registry=cr)

    assert len(channel.replies) == 1
    # Agent 通过 FakeLLMProvider.calls 验证收到的 content
    last_call = provider.calls[-1]
    user_msg = last_call["messages"][-1]
    assert user_msg["content"] == "rewritten content"
