"""N1 统一 MemoryItem 业务测试。

覆盖:
- MemoryItem.from_episode/to_episode 完整字段映射 (含 summary/topics/participants/emotion)
- MemoryItem.from_profile/to_profile (含 traits/relationship_depth/interaction_count)
- MemoryItem.from_jargon/to_jargon (含 word/context/usage_count)
- MemoryItemAdapter.to_hit (MemoryItem → MemoryHit)
- MemoryItemAdapter.from_hit (MemoryHit → MemoryItem)
- 未知列优雅降级 (默认值)
"""

from __future__ import annotations

from isac.core.types import MemoryHit
from isac.memory.model.adapter import MemoryItemAdapter
from isac.memory.model.memory_item import MemoryItem, MemoryScope, MemoryType


def _episode_row(**kw: object) -> dict[str, object]:
    """构造 episodes 表的一行 (dict), 缺省字段用合理默认值."""
    base: dict[str, object] = {
        "id": "ep1",
        "agent_id": "a1",
        "session_id": "s1",
        "user_id": "u1",
        "content": "用户讨论了周末计划",
        "summary": "周末计划讨论",
        "topics": '["周末","计划"]',
        "participants": '["u1","u2"]',
        "emotion": "neutral",
        "importance": 0.8,
        "created_at": 1700000000,
        "updated_at": 1700000100,
        "group_id": "g1",
    }
    base.update(kw)
    return base


def _profile_row(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "agent_id": "a1",
        "person_id": "p1",
        "name": "张三",
        "profile_text": "工程师, 喜欢科幻",
        "traits": '["理性","好奇"]',
        "relationship_depth": 0.6,
        "interaction_count": 12,
        "first_seen": 1699000000,
        "last_seen": 1700000000,
        "embedding_hash": "abc123",
    }
    base.update(kw)
    return base


def _jargon_row(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "agent_id": "a1",
        "word": "emo",
        "meaning": "情绪低落",
        "context": "群聊常用",
        "usage_count": 5,
        "created_at": 1700000000,
    }
    base.update(kw)
    return base


# ── from_episode / to_episode ────────────────────────────────────


def test_from_episode_full_field_mapping() -> None:
    row = _episode_row()
    item = MemoryItem.from_episode(row)
    assert item.id == "ep1"
    assert item.agent_id == "a1"
    assert item.scope is MemoryScope.AGENT_PRIVATE
    assert item.subject_id == "u1"
    assert item.content == "用户讨论了周末计划"
    assert item.memory_type is MemoryType.EPISODE
    assert item.importance == 0.8
    assert item.created_at == 1700000000
    # summary/topics/participants/emotion 进 metadata
    assert item.metadata["summary"] == "周末计划讨论"
    assert item.metadata["emotion"] == "neutral"
    assert item.metadata["session_id"] == "s1"
    assert item.metadata["group_id"] == "g1"


def test_to_episode_roundtrip_preserves_known_fields() -> None:
    row = _episode_row()
    item = MemoryItem.from_episode(row)
    back = item.to_episode()
    assert back["id"] == "ep1"
    assert back["agent_id"] == "a1"
    assert back["user_id"] == "u1"
    assert back["content"] == "用户讨论了周末计划"
    assert back["importance"] == 0.8
    assert back["created_at"] == 1700000000


def test_from_episode_unknown_columns_default_safely() -> None:
    """缺列时用默认值, 不抛."""
    item = MemoryItem.from_episode({"id": "ep1", "agent_id": "a1"})
    assert item.id == "ep1"
    assert item.content == ""
    assert item.importance == 0.0
    assert item.created_at == 0


# ── from_profile / to_profile ────────────────────────────────────


def test_from_profile_full_field_mapping() -> None:
    row = _profile_row()
    item = MemoryItem.from_profile(row)
    assert item.agent_id == "a1"
    assert item.scope is MemoryScope.USER_GLOBAL
    assert item.subject_id == "p1"
    assert item.content == "工程师, 喜欢科幻"
    assert item.memory_type is MemoryType.PROFILE
    assert item.metadata["name"] == "张三"
    assert item.metadata["traits"] == '["理性","好奇"]'
    assert item.metadata["relationship_depth"] == 0.6
    assert item.metadata["interaction_count"] == 12


def test_to_profile_roundtrip_preserves_known_fields() -> None:
    row = _profile_row()
    item = MemoryItem.from_profile(row)
    back = item.to_profile()
    assert back["agent_id"] == "a1"
    assert back["person_id"] == "p1"
    assert back["profile_text"] == "工程师, 喜欢科幻"
    assert back["name"] == "张三"
    assert back["relationship_depth"] == 0.6


# ── from_jargon / to_jargon ───────────────────────────────────────


def test_from_jargon_full_field_mapping() -> None:
    row = _jargon_row()
    item = MemoryItem.from_jargon(row)
    assert item.agent_id == "a1"
    assert item.scope is MemoryScope.AGENT_PRIVATE
    assert item.subject_id == "a1"  # jargon 是 Agent 私有, subject_id = agent_id
    assert item.content == "情绪低落"  # meaning → content
    assert item.memory_type is MemoryType.JARGON
    assert item.metadata["word"] == "emo"
    assert item.metadata["context"] == "群聊常用"
    assert item.metadata["usage_count"] == 5


def test_to_jargon_roundtrip_preserves_known_fields() -> None:
    row = _jargon_row()
    item = MemoryItem.from_jargon(row)
    back = item.to_jargon()
    assert back["agent_id"] == "a1"
    assert back["word"] == "emo"
    assert back["meaning"] == "情绪低落"
    assert back["usage_count"] == 5


# ── MemoryItemAdapter: MemoryItem ↔ MemoryHit ───────────────────


def test_adapter_to_hit_converts_memoryitem_to_memoryhit() -> None:
    item = MemoryItem(
        id="ep1",
        agent_id="a1",
        scope=MemoryScope.AGENT_PRIVATE,
        subject_id="u1",
        content="周末计划",
        memory_type=MemoryType.EPISODE,
        importance=0.8,
        metadata={"session_id": "s1"},
    )
    hit = MemoryItemAdapter.to_hit(item, score=0.95)
    assert isinstance(hit, MemoryHit)
    assert hit.id == "ep1"
    assert hit.content == "周末计划"
    assert hit.source == "s1"
    assert hit.hit_type == "episode"
    assert hit.score == 0.95
    assert hit.metadata["importance"] == 0.8


def test_adapter_from_hit_converts_memoryhit_to_memoryitem() -> None:
    hit = MemoryHit(
        id="ep1",
        content="周末计划",
        source="s1",
        hit_type="episode",
        score=0.95,
        metadata={"agent_id": "a1", "importance": 0.8},
    )
    item = MemoryItemAdapter.from_hit(hit)
    assert item.id == "ep1"
    assert item.content == "周末计划"
    assert item.agent_id == "a1"
    assert item.subject_id == "s1"  # source = session_id → subject_id
    assert item.memory_type is MemoryType.EPISODE
    assert item.importance == 0.8


def test_adapter_from_hit_unknown_hit_type_defaults_episode() -> None:
    """未知 hit_type 时默认 EPISODE, 不抛."""
    hit = MemoryHit(id="x1", content="x", source="s1", hit_type="unknown_type", score=0.5)
    item = MemoryItemAdapter.from_hit(hit)
    assert item.memory_type is MemoryType.EPISODE
