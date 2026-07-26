"""runtime/assembly 单元测试。"""

from __future__ import annotations

import pytest

from isac.channel.model import ISACMessage
from isac.core.types import InjectionContext
from isac.gateway.models import Session
from isac.memory.pipeline import NoOpMemoryPipeline
from isac.provider.llm.stub import StubProvider
from isac.provider.manager import ProviderManager
from isac.runtime.assembly import assemble_agent
from isac.runtime.config import AgentConfig


@pytest.mark.asyncio
async def test_assemble_agent_registers_safe_tools_and_memory_injectors() -> None:
    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    agent = await assemble_agent(
        AgentConfig(agent_id="agent_a"),
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        },
    )

    tool_names = {definition["name"] for definition in agent.tools.definitions()}
    injector_keys = {injector.key for injector in agent.prompt_builder._injectors}

    assert {"query_memory", "query_person_profile", "wait", "ask_agent"}.issubset(tool_names)
    assert {"person_profile", "jargon", "heuristic_memory", "mid_term_memory"}.issubset(injector_keys)
    assert agent.services["memory"].namespace == "agent_a"


@pytest.mark.asyncio
async def test_assembled_services_agent_id_matches_instance_agent_id() -> None:
    """CR2-Fix-1: agent_services["agent_id"] 必须与 AgentInstance.agent_id 一致,
    否则 wait 工具 (从 services 取 agent_id) 和 manager._dispatch_message (从
    instance.agent_id 取) 会用不同的 key 操作 ConversationRuntimeRegistry,
    互相唤醒不到对方。"""
    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    agent = await assemble_agent(
        AgentConfig(agent_id="agent_c"),
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        },
    )

    assert agent.services["agent_id"] == agent.agent_id == "agent_c"


@pytest.mark.asyncio
async def test_assemble_agent_registers_interrupt_and_recovery_injectors() -> None:
    """CR2-Fix-8: InterruptInjector/RecoveryInjector 此前从未被注册进
    prompt_builder, 即使 ConversationRuntime.request_interrupt 被调用, 打断
    提示也永远不会出现在 System Prompt 里。"""
    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    agent = await assemble_agent(
        AgentConfig(agent_id="agent_d"),
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        },
    )
    injector_keys = {injector.key for injector in agent.prompt_builder._injectors}
    assert {"interrupt_hint", "recovery_hint"}.issubset(injector_keys)


def _injection_context(session_id: str = "s1") -> InjectionContext:
    session = Session(session_id=session_id, user_id="u1", platform="webchat")
    message = ISACMessage(msg_id="m1", platform="webchat", timestamp=0, user_id="u1", user_name="u", content="hi")
    return InjectionContext(session=session, user_profile=None, current_message=message)


@pytest.mark.asyncio
async def test_interrupt_injector_zero_behavior_when_conversation_disabled() -> None:
    """conversation.enabled=False (默认) 时不应创建任何 ConversationRuntime 实例,
    保持零行为变化。"""
    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    agent = await assemble_agent(
        AgentConfig(agent_id="agent_e"),
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},  # conversation.enabled 默认 False
        },
    )
    prompt = await agent.prompt_builder.build(_injection_context())
    assert "打断" not in prompt
    registry = agent.services["conversation_registry"]
    assert len(registry) == 0  # 未创建任何 ConversationRuntime 实例


@pytest.mark.asyncio
async def test_interrupt_injector_surfaces_hint_when_conversation_enabled_and_interrupted() -> None:
    """conversation.enabled=True 且该 session 的 runtime 已被 request_interrupt
    后, InterruptInjector 应能查到对应 runtime 并注入提示 (证明"即使触发了打断
    也不会显示"这个独立缺口被修复; 生产链路何时调用 request_interrupt 是另一
    个未接线的问题, 不在本次修复范围)。"""
    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    agent = await assemble_agent(
        AgentConfig(agent_id="agent_f"),
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {"conversation": {"enabled": True}},
        },
    )
    registry = agent.services["conversation_registry"]
    runtime = registry.get("agent_f", "s1")
    runtime.request_interrupt(reason="用户发了新消息")
    prompt = await agent.prompt_builder.build(_injection_context("s1"))
    assert "打断" in prompt


@pytest.mark.asyncio
async def test_progress_reporter_factory_wires_resolved_llm_for_llm_rendering() -> None:
    """D9-6: persona_rendering="llm" 时, 工厂构造的 Reporter 应复用本 Agent 已解析的
    llm Provider (与 loop.llm 同一个实例), 而不是重新创建或留空。"""
    provider_manager = ProviderManager({})
    stub = StubProvider()
    provider_manager.register(stub)
    agent = await assemble_agent(
        AgentConfig(agent_id="agent_b", persona={"progress": {"persona_rendering": "llm"}}),
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        },
    )

    factory = agent.services["progress_reporter_factory"]
    reporter = factory("sess_1")

    assert reporter.renderer._llm is agent.loop.llm
