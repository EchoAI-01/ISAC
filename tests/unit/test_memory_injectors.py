"""记忆注入器单元测试。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from isac.core.types import InjectionContext, MemoryHit
from isac.gateway.models import Session, UserProfile
from isac.memory.injector.heuristic import HeuristicMemoryInjector
from isac.memory.injector.jargon import JargonInjector
from isac.memory.injector.mid_term import MidTermMemoryInjector
from isac.memory.injector.person_profile import PersonProfileInjector


class FakeMetadata:
    async def get_person_profile(self, agent_id: str, person_id: str) -> dict | None:
        return {
            "person_id": person_id,
            "name": "小明",
            "profile_text": "喜欢先完善文档再写代码",
            "relationship_depth": 0.7,
        }

    async def list_jargon(self, agent_id: str) -> list[dict]:
        return [{"word": "施工图", "meaning": "可执行的详细设计", "context": "架构文档", "usage_count": 1}]


class FakePipeline:
    def __init__(self) -> None:
        self.namespace = "agent_a"
        self.metadata = FakeMetadata()

    async def search(self, query: str, top_k: int = 5, **kwargs) -> list[MemoryHit]:
        return [MemoryHit(id="mem_1", content=f"相关记忆: {query}", source="sess_1", hit_type="episode", score=0.9)]


class FailingPipeline(FakePipeline):
    async def search(self, query: str, top_k: int = 5, **kwargs) -> list[MemoryHit]:
        raise RuntimeError("boom")


@dataclass
class Message:
    content: str = "我们继续补施工图"


def make_context(*, pending_count: int = 0) -> InjectionContext:
    pending = [Message(content=f"第 {index} 条消息") for index in range(pending_count)]
    return InjectionContext(
        session=Session(session_id="sess_1", user_id="user_1", agent_id="agent_a"),
        user_profile=UserProfile(user_id="user_1", nickname="小明"),
        current_message=Message(),
        pending_messages=pending,
    )


@pytest.mark.asyncio
async def test_heuristic_memory_injector_formats_internal_reference() -> None:
    text = await HeuristicMemoryInjector(FakePipeline()).build(make_context())

    assert "【启发式记忆-内部参考】" in text
    assert "相关记忆" in text
    assert "不要向用户逐字复述" in text


@pytest.mark.asyncio
async def test_memory_injector_failure_returns_empty_string() -> None:
    text = await HeuristicMemoryInjector(FailingPipeline()).build(make_context())

    assert text == ""


@pytest.mark.asyncio
async def test_person_profile_injector_formats_profile() -> None:
    text = await PersonProfileInjector(FakePipeline()).build(make_context())

    assert "【人物画像-内部参考】" in text
    assert "小明" in text
    assert "喜欢先完善文档再写代码" in text


@pytest.mark.asyncio
async def test_jargon_injector_matches_current_message() -> None:
    text = await JargonInjector(FakePipeline()).build(make_context())

    assert "【行话-内部参考】" in text
    assert "施工图" in text
    assert "可执行的详细设计" in text


@pytest.mark.asyncio
async def test_mid_term_memory_injector_summarizes_pending_messages() -> None:
    text = await MidTermMemoryInjector(FakePipeline()).build(make_context(pending_count=2))

    assert "【中期记忆-内部参考】" in text
    assert "第 0 条消息" in text
    assert "第 1 条消息" in text
