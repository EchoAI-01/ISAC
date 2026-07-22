"""记忆注入器频率控制测试。"""

from __future__ import annotations

import pytest

from isac.agent.prompt_builder import SystemPromptBuilder
from isac.core.types import InjectionContext, MemoryHit
from isac.gateway.models import Session
from isac.memory.injector.heuristic import HeuristicMemoryInjector


class FakePipeline:
    namespace = "agent_a"

    async def search(self, query: str, top_k: int = 5, **kwargs) -> list[MemoryHit]:
        return [MemoryHit(id="mem_1", content="长期记忆", source="sess_1", hit_type="episode", score=1.0)]


class Message:
    content = "继续讨论记忆"


def make_context() -> InjectionContext:
    return InjectionContext(
        session=Session(session_id="sess_1", user_id="user_1", agent_id="agent_a"),
        user_profile=None,
        current_message=Message(),
    )


@pytest.mark.asyncio
async def test_heuristic_memory_requires_enough_new_messages() -> None:
    builder = SystemPromptBuilder()
    builder.register(HeuristicMemoryInjector(FakePipeline()))

    assert await builder.build(make_context()) == ""

    for _ in range(60):
        builder.notify_new_message()

    prompt = await builder.build(make_context())

    assert "【启发式记忆-内部参考】" in prompt
