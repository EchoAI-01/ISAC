"""N1/N2 记忆模型与治理骨架测试。

验证 N1 统一 MemoryItem 契约与 episode 适配、N2 MemoryGovernor 治理动作骨架
(no-op) 与 routes_memory_admin 无 store 时不挂载。真实迁移与治理属实现节点
(N1/N2), 本文件只覆盖骨架级行为。
"""

from __future__ import annotations

from isac.memory.model import MemoryGovernor, MemoryItem, MemoryScope, MemoryType


def test_memory_type_and_scope_values() -> None:
    assert {t.value for t in MemoryType} == {
        "episode", "fact", "profile", "relationship", "jargon", "preference", "self"
    }
    assert MemoryScope.AGENT_PRIVATE.value == "agent_private"
    assert MemoryScope.ORGANIZATION in set(MemoryScope)


def test_memory_item_defaults() -> None:
    item = MemoryItem(
        id="m1", agent_id="a1", scope=MemoryScope.AGENT_PRIVATE,
        subject_id="u1", content="hi", memory_type=MemoryType.EPISODE,
    )
    assert item.confidence == 1.0
    assert item.importance == 0.0
    assert item.expires_at is None
    assert item.frozen is False and item.protected is False
    assert item.source_message_ids == [] and item.metadata == {}


def test_memory_item_from_episode_maps_known_columns() -> None:
    row = {"id": "e1", "agent_id": "a1", "user_id": "u1", "content": "聊了天气", "importance": 0.5, "created_at": 123}
    item = MemoryItem.from_episode(row)
    assert item.id == "e1"
    assert item.agent_id == "a1"
    assert item.subject_id == "u1"
    assert item.memory_type is MemoryType.EPISODE
    assert item.scope is MemoryScope.AGENT_PRIVATE
    assert item.importance == 0.5
    assert item.created_at == 123


def test_memory_item_to_episode_round_trips_core_fields() -> None:
    item = MemoryItem.from_episode({"id": "e1", "agent_id": "a1", "user_id": "u1", "content": "x"})
    row = item.to_episode()
    assert row["id"] == "e1" and row["agent_id"] == "a1" and row["user_id"] == "u1"


async def test_governor_actions_are_noop_by_default() -> None:
    gov = MemoryGovernor()
    assert await gov.freeze("m1", "a1") is False
    assert await gov.protect("m1", "a1") is False
    assert await gov.correct("m1", "new", "a1") is False
    assert await gov.delete("m1", "a1") is False
    assert await gov.restore("m1", "a1") is False
    assert await gov.export("a1") == []


def test_memory_admin_router_not_mounted_without_store() -> None:
    from isac.control.api import routes_memory_admin

    assert routes_memory_admin.build_router(None) is None
