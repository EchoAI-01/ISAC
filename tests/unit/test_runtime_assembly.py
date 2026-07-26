"""runtime/assembly 单元测试。"""

from __future__ import annotations

import pytest

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
