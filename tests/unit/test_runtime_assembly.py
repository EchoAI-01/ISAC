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
