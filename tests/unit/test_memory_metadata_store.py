"""MetadataStore 单元测试。"""

from __future__ import annotations

import pytest

from isac.memory.storage.metadata import MetadataStore


@pytest.mark.asyncio
async def test_store_episode_and_search_fts_are_agent_isolated(tmp_path) -> None:
    store = MetadataStore(str(tmp_path / "memory.db"))
    await store.init_schema()

    await store.store_episode(
        "agent_a",
        {
            "id": "mem_a",
            "session_id": "sess_a",
            "user_id": "user_a",
            "content": "ISAC 正在补齐记忆系统施工图",
            "summary": "记忆系统施工图",
            "topics": ["ISAC", "记忆"],
            "participants": ["user_a"],
            "importance": 0.8,
        },
    )
    await store.store_episode(
        "agent_b",
        {
            "id": "mem_b",
            "session_id": "sess_b",
            "user_id": "user_b",
            "content": "另一个 Agent 的私有记忆",
            "summary": "私有记忆",
        },
    )

    results = await store.search_fts("agent_a", "ISAC 记忆", limit=5)

    assert [item["id"] for item in results] == ["mem_a"]
    assert results[0]["content"] == "ISAC 正在补齐记忆系统施工图"


@pytest.mark.asyncio
async def test_person_profile_upsert_and_read(tmp_path) -> None:
    store = MetadataStore(str(tmp_path / "memory.db"))
    await store.init_schema()

    await store.upsert_person_profile(
        "agent_a",
        {
            "person_id": "user_1",
            "name": "小明",
            "profile_text": "喜欢先完善文档再写代码",
            "traits": ["重视架构"],
            "relationship_depth": 0.7,
            "interaction_count": 3,
        },
    )

    profile = await store.get_person_profile("agent_a", "user_1")

    assert profile is not None
    assert profile["name"] == "小明"
    assert profile["traits"] == ["重视架构"]
    assert profile["relationship_depth"] == 0.7


@pytest.mark.asyncio
async def test_jargon_upsert_and_list(tmp_path) -> None:
    store = MetadataStore(str(tmp_path / "memory.db"))
    await store.init_schema()

    await store.upsert_jargon("agent_a", "施工图", "可执行的详细设计", context="文档规划")

    entries = await store.list_jargon("agent_a")

    assert entries == [
        {
            "word": "施工图",
            "meaning": "可执行的详细设计",
            "context": "文档规划",
            "usage_count": 1,
        }
    ]
