"""MetadataStore 单元测试。"""

from __future__ import annotations

import aiosqlite
import pytest

from isac.memory.storage.metadata import MetadataStore

_LEGACY_EPISODES_SCHEMA = """
CREATE TABLE episodes (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,
    topics TEXT,
    participants TEXT,
    emotion TEXT,
    importance REAL DEFAULT 0.5,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE VIRTUAL TABLE episodes_fts USING fts5(
    content, summary, topics, participants,
    content=episodes, content_rowid=rowid
);
"""


@pytest.mark.asyncio
async def test_init_schema_migrates_legacy_db_missing_group_id_column(tmp_path) -> None:
    """老库没有 group_id 列 (ALTER TABLE ADD COLUMN 无 IF NOT EXISTS, 需先探测)。"""
    db_path = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_LEGACY_EPISODES_SCHEMA)
        await db.commit()

    store = MetadataStore(db_path)
    await store.init_schema()  # 不应因列已存在的部分表结构而报错
    await store.init_schema()  # 再次调用 (幂等) 也不应报错

    memory_id = await store.store_episode(
        "agent_a",
        {"id": "mem_1", "session_id": "sess_1", "user_id": "user_1", "group_id": "group_1", "content": "迁移后可用"},
    )
    results = await store.search_fts("agent_a", "迁移后可用", limit=5, group_id="group_1")

    assert memory_id == "mem_1"
    assert [item["id"] for item in results] == ["mem_1"]


@pytest.mark.asyncio
async def test_store_episode_update_syncs_fts_incrementally(tmp_path) -> None:
    """写入后 FTS 由触发器增量同步; 用同一 id 覆盖写入后, 旧内容不再可检索、新内容可检索

    (CODE_REVIEW_REPORT.md #12: 取代写入路径上的全量 rebuild)。
    """
    store = MetadataStore(str(tmp_path / "memory.db"))
    await store.init_schema()

    # 新旧内容用互斥的锚点词 (ALPHAOLD/ALPHANEW), 避免 _fts_query() 的 OR 语义
    # 让共享词汇 (如同为 "ISAC") 掩盖掉本应验证的"旧内容不再可查"这一行为。
    await store.store_episode(
        "agent_a",
        {"id": "mem_1", "session_id": "sess_1", "user_id": "user_1", "content": "ALPHAOLD 施工图"},
    )
    before = await store.search_fts("agent_a", "ALPHAOLD", limit=5)
    assert [item["id"] for item in before] == ["mem_1"]

    await store.store_episode(
        "agent_a",
        {"id": "mem_1", "session_id": "sess_1", "user_id": "user_1", "content": "ALPHANEW 施工图"},
    )

    after_old_query = await store.search_fts("agent_a", "ALPHAOLD", limit=5)
    after_new_query = await store.search_fts("agent_a", "ALPHANEW", limit=5)
    assert after_old_query == []
    assert [item["id"] for item in after_new_query] == ["mem_1"]
    assert after_new_query[0]["content"] == "ALPHANEW 施工图"


@pytest.mark.asyncio
async def test_store_episode_update_leaves_no_orphaned_fts_index_entry(tmp_path) -> None:
    """覆盖写入后, episodes_fts 倒排索引本身不应残留旧 rowid 的词项。

    search_fts() 因为 JOIN episodes 会自然过滤掉指向已删除行的孤儿索引项, 但孤儿项
    本身仍会占用索引空间并污染 bm25() 的文档频率统计, 因此直接对 episodes_fts 发
    MATCH 查询验证 (不经过 JOIN), 而不仅仅依赖 search_fts() 的返回结果。
    """
    db_path = str(tmp_path / "memory.db")
    store = MetadataStore(db_path)
    await store.init_schema()

    await store.store_episode(
        "agent_a",
        {"id": "mem_1", "session_id": "sess_1", "user_id": "user_1", "content": "ALPHAOLD 施工图"},
    )
    await store.store_episode(
        "agent_a",
        {"id": "mem_1", "session_id": "sess_1", "user_id": "user_1", "content": "ALPHANEW 施工图"},
    )

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT rowid FROM episodes_fts WHERE episodes_fts MATCH 'ALPHAOLD'")
        stale_rows = await cursor.fetchall()

    assert stale_rows == []


@pytest.mark.asyncio
async def test_rebuild_fts_index_is_available_for_ops_use(tmp_path) -> None:
    """rebuild_fts_index() 保留作为运维修复入口 (不在写入路径调用), 调用后索引仍可用。"""
    store = MetadataStore(str(tmp_path / "memory.db"))
    await store.init_schema()
    await store.store_episode(
        "agent_a",
        {"id": "mem_1", "session_id": "sess_1", "user_id": "user_1", "content": "ISAC 运维重建"},
    )

    await store.rebuild_fts_index()

    results = await store.search_fts("agent_a", "ISAC 运维重建", limit=5)
    assert [item["id"] for item in results] == ["mem_1"]


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
async def test_search_fts_private_chat_is_isolated_per_user(tmp_path) -> None:
    """同一 agent 下, 私聊记忆 (group_id 为空) 应仅对发言者本人可见 (CODE_REVIEW_REPORT.md #9)。"""
    store = MetadataStore(str(tmp_path / "memory.db"))
    await store.init_schema()

    await store.store_episode(
        "agent_a",
        {"id": "mem_user_a", "session_id": "sess_a", "user_id": "user_a", "content": "ISAC 私聊记忆 来自 user_a"},
    )
    await store.store_episode(
        "agent_a",
        {"id": "mem_user_b", "session_id": "sess_b", "user_id": "user_b", "content": "ISAC 私聊记忆 来自 user_b"},
    )

    results_a = await store.search_fts("agent_a", "ISAC 私聊记忆", limit=5, user_id="user_a")

    assert [item["id"] for item in results_a] == ["mem_user_a"]


@pytest.mark.asyncio
async def test_search_fts_group_chat_is_shared_across_members(tmp_path) -> None:
    """同一 agent 下, 群聊记忆 (group_id 非空) 应对该群全部成员可见, 不按发言人收窄。"""
    store = MetadataStore(str(tmp_path / "memory.db"))
    await store.init_schema()

    await store.store_episode(
        "agent_a",
        {
            "id": "mem_group_1",
            "session_id": "sess_g1",
            "user_id": "user_a",
            "group_id": "group_1",
            "content": "群聊共享记忆 来自 user_a",
        },
    )
    await store.store_episode(
        "agent_a",
        {
            "id": "mem_group_2",
            "session_id": "sess_g1",
            "user_id": "user_b",
            "group_id": "group_1",
            "content": "群聊共享记忆 来自 user_b",
        },
    )
    await store.store_episode(
        "agent_a",
        {
            "id": "mem_other_group",
            "session_id": "sess_g2",
            "user_id": "user_c",
            "group_id": "group_2",
            "content": "群聊共享记忆 来自另一个群",
        },
    )

    # user_c 本人未曾在 group_1 发言, 但因为身处该群, 传 group_id 后应看到全部成员的记忆。
    results = await store.search_fts("agent_a", "群聊共享记忆", limit=10, user_id="user_c", group_id="group_1")

    assert {item["id"] for item in results} == {"mem_group_1", "mem_group_2"}


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
