"""P4 身份归一集成测试 (R7-②)。

端到端验证跨平台同一自然人经 IdentityResolver.bind 归一到统一 person_id 后,
记忆按归一身份聚合: 两平台 (qq + telegram) 写入的 episode 用归一 master_id 落库,
检索时按该 master_id 一次取回两平台记忆 (pipeline.search 按 platform user_id 过滤,
故跨平台聚合需调用方写入时统一用 master_id, 即 gateway 主链路真实写入路径)。

补充: 低置信冲突经 arbitrate_conflict 写 identity_conflicts 供人工裁决 + resolve_conflict 解决。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest

from isac.gateway.identity.models import PersonIdentity, PlatformIdentity
from isac.gateway.identity.resolver import IdentityResolver
from isac.gateway.user_mapper import UserMapper
from isac.memory.embedder import EmbeddingManager
from isac.memory.pipeline import MemoryRetrievalPipeline
from isac.memory.reranker import Reranker
from isac.memory.storage.graph import GraphStore
from isac.memory.storage.metadata import MetadataStore
from isac.memory.storage.sparse import SparseBM25Index
from isac.memory.storage.vector import VectorStore

NAMESPACE = "agent_p4"


@pytest.fixture
async def env(tmp_path: Path) -> AsyncGenerator[dict[str, Any], None]:
    """构造 IdentityResolver + UserMapper + MemoryRetrievalPipeline (FTS 主召回)。"""
    mapper = UserMapper(str(tmp_path / "users.db"))
    resolver = IdentityResolver(mapper, heuristic_enabled=False, db_path=str(tmp_path / "identity.db"))
    await resolver._ensure_schema()  # noqa: SLF001 — 触发建表
    metadata = MetadataStore(str(tmp_path / "memory.db"))
    await metadata.init_schema()
    pipeline = MemoryRetrievalPipeline(
        namespace=NAMESPACE,
        metadata=metadata,
        vector=VectorStore(str(tmp_path / "vectors.db"), dimension=3),
        sparse=SparseBM25Index(),
        graph=GraphStore(str(tmp_path / "graph.db")),
        embedder=EmbeddingManager({}),  # 降级: 跨平台聚合测试走 FTS, 不需向量
        reranker=Reranker({}),
        enable_graph_recall=False,
    )
    yield {"resolver": resolver, "mapper": mapper, "pipeline": pipeline}
    await pipeline.vector.close()
    await pipeline.graph.close()


# ── 跨平台 bind → 记忆聚合 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_two_platforms_bind_to_same_person(env: dict[str, Any]) -> None:
    """qq 与 telegram 两个平台账号绑定到同一 person_id; resolve 两平台都返回该 person。"""
    resolver: IdentityResolver = env["resolver"]
    person_id = "person_alice"
    # 先在 UserMapper 建 person profile (bind 要求 master_id 已存在)
    await env["mapper"].resolve("qq", "qq_alice", "Alice")  # 创建 person_alice profile
    # 把 qq + telegram 两个平台账号都绑到同一 person
    ok1 = await resolver.bind(person_id, PlatformIdentity(
        platform="qq", connection_id="c1", platform_user_id="qq_alice", display_name="Alice"))
    ok2 = await resolver.bind(person_id, PlatformIdentity(
        platform="telegram", connection_id="c2", platform_user_id="tg_alice", display_name="Alice"))
    assert ok1 and ok2
    # resolve 两平台都归一到 person_alice
    assert await resolver.resolve("qq", "qq_alice") == person_id
    assert await resolver.resolve("telegram", "tg_alice") == person_id


@pytest.mark.asyncio
async def test_memory_aggregates_under_unified_identity(env: dict[str, Any]) -> None:
    """两平台写入 episode 用归一 master_id 落库 → 按该 master_id 一次检索取回两平台记忆。

    pipeline.search 按 platform user_id 过滤; 跨平台聚合需调用方写入时统一用
    归一 person_id (即 gateway 主链路经 IdentityResolver.resolve 得 master_id 后写入)。
    """
    resolver: IdentityResolver = env["resolver"]
    pipeline: MemoryRetrievalPipeline = env["pipeline"]
    person_id = "person_bob"
    await env["mapper"].resolve("qq", "qq_bob", "Bob")
    await resolver.bind(person_id, PlatformIdentity(
        platform="qq", connection_id="c1", platform_user_id="qq_bob", display_name="Bob"))
    await resolver.bind(person_id, PlatformIdentity(
        platform="telegram", connection_id="c2", platform_user_id="tg_bob", display_name="Bob"))
    # 模拟 gateway 写入路径: 用归一 person_id 作为 user_id 落库 (两平台记忆同 key)。
    # 两 episode 共享查询词 "项目x" 以验证按归一身份一次检索取回两平台记忆。
    mid_qq = await pipeline.store_episode(
        "我在 qq 讨论了 项目x 发布流程", "sess1", user_id=person_id, agent_id=NAMESPACE)
    mid_tg = await pipeline.store_episode(
        "我在 telegram 补充了 项目x 回滚预案", "sess2", user_id=person_id, agent_id=NAMESPACE)
    assert mid_qq and mid_tg
    # 按归一身份检索共享词 → 两平台记忆都命中 (聚合在统一 user_id 下)
    hits = await pipeline.search("项目x", top_k=10, user_id=person_id, agent_id=NAMESPACE)
    ids = {h.id for h in hits}
    assert mid_qq in ids and mid_tg in ids, "两平台记忆应按归一 person_id 聚合检索"


@pytest.mark.asyncio
async def test_memory_isolated_by_identity(env: dict[str, Any]) -> None:
    """归一身份隔离: alice 的记忆用 person_alice 检索, bob 的记忆用 person_bob 检索, 互不可见。"""
    resolver: IdentityResolver = env["resolver"]
    pipeline: MemoryRetrievalPipeline = env["pipeline"]
    await env["mapper"].resolve("qq", "u_a", "Alice")
    await env["mapper"].resolve("qq", "u_b", "Bob")
    await resolver.bind("person_alice", PlatformIdentity(
        platform="qq", connection_id="ca", platform_user_id="u_a", display_name="Alice"))
    await resolver.bind("person_bob", PlatformIdentity(
        platform="qq", connection_id="cb", platform_user_id="u_b", display_name="Bob"))
    mid_a = await pipeline.store_episode(
        "alice 的私密记忆片段", "sa", user_id="person_alice", agent_id=NAMESPACE)
    mid_b = await pipeline.store_episode(
        "bob 的私密记忆片段", "sb", user_id="person_bob", agent_id=NAMESPACE)
    # alice 检索只看到自己的
    hits_a = await pipeline.search("私密记忆", top_k=10, user_id="person_alice", agent_id=NAMESPACE)
    ids_a = {h.id for h in hits_a}
    assert mid_a in ids_a and mid_b not in ids_a, "归一身份隔离: alice 不应看到 bob 记忆"


# ── 低置信冲突 → identity_conflicts ────────────────────────────────


@pytest.mark.asyncio
async def test_low_confidence_writes_conflict_for_manual_arbitration(env: dict[str, Any]) -> None:
    """arbitrate_conflict 收到 confidence<0.7 候选时写 identity_conflicts 供人工裁决。"""
    resolver: IdentityResolver = env["resolver"]
    candidates = [
        PersonIdentity(person_id="person_x", confidence=0.4, verified=False, aliases=["x"]),
        PersonIdentity(person_id="person_y", confidence=0.3, verified=False, aliases=["y"]),
    ]
    winner = resolver.arbitrate_conflict(candidates)
    assert winner is not None and winner.person_id == "person_x"  # 取最高 confidence
    conflicts = resolver.list_conflicts()
    assert len(conflicts) == 1, "低置信冲突应写入 identity_conflicts"
    assert conflicts[0]["person_id"] == "person_x"
    assert not conflicts[0]["resolved"], "新冲突应未解决"


@pytest.mark.asyncio
async def test_resolve_conflict_marks_resolved(env: dict[str, Any]) -> None:
    """resolve_conflict 把冲突标记为已解决 (不再出现在 list_conflicts)。"""
    resolver: IdentityResolver = env["resolver"]
    candidates = [
        PersonIdentity(person_id="person_z", confidence=0.2, verified=False, aliases=["z"]),
    ]
    resolver.arbitrate_conflict(candidates)
    conflicts = resolver.list_conflicts()
    assert conflicts
    conflict_id = conflicts[0]["conflict_id"]
    ok = await resolver.resolve_conflict(conflict_id, "person_z")
    assert ok, "resolve_conflict 应成功"
    remaining = resolver.list_conflicts()
    assert all(c["conflict_id"] != conflict_id for c in remaining), "已解决冲突不应再出现在未裁决列表"


# 高置信候选不写冲突
@pytest.mark.asyncio
async def test_high_confidence_does_not_write_conflict(env: dict[str, Any]) -> None:
    """confidence≥0.7 的高置信候选不写 identity_conflicts (直接采纳, 无需人工)。"""
    resolver: IdentityResolver = env["resolver"]
    candidates = [
        PersonIdentity(person_id="person_hi", confidence=0.9, verified=True, aliases=["hi"]),
        PersonIdentity(person_id="person_mid", confidence=0.75, verified=False, aliases=["mid"]),
    ]
    resolver.arbitrate_conflict(candidates)
    assert resolver.list_conflicts() == [], "高置信候选不应写冲突记录"
