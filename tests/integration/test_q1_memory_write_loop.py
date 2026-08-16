"""Q1: 记忆写入回路与身份稳定化集成测试 (DEVELOPMENT_PLAN.md §四 Q1)。

验收对应:
- 聊天 → episodic 真实写入 → "重启" (新 pipeline 预热) → 检索命中
- 画像随互动加深 (interaction_count / relationship_depth 递增, 读写同键)
- UserMapper SQLite 持久化: 重启后同平台账号解析出同一 master_id (person_id 稳定)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from isac.channel.model import ISACMessage, MessageSegment
from isac.channel.registry import ChannelRegistry
from isac.gateway.event_bus import EventBus
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.main import process_message
from isac.memory.embedder import EmbeddingManager
from isac.memory.pipeline import MemoryRetrievalPipeline
from isac.memory.storage.graph import GraphStore
from isac.memory.storage.metadata import MetadataStore
from isac.memory.storage.sparse import SparseBM25Index
from isac.memory.storage.vector import VectorStore
from isac.observability import get_default_metrics
from isac.provider.manager import ProviderManager
from isac.router.router import MessageRouter
from isac.router.types import RoutingRules
from isac.runtime.config import AgentConfig
from isac.runtime.manager import AgentManager
from tests.fixtures.fakes import FakeChannel, FakeLLMProvider, make_final_reply


def _make_memory_factory(tmp_path: Path):
    """真实 MemoryRetrievalPipeline 工厂 (共享 MetadataStore, 降级 embedder 纯稀疏)。"""
    metadata_store = MetadataStore(str(tmp_path / "metadata.db"))
    sparse_indexes: dict[str, SparseBM25Index] = {}

    def factory(namespace: str) -> MemoryRetrievalPipeline:
        return MemoryRetrievalPipeline(
            namespace=namespace,
            metadata=metadata_store,
            vector=VectorStore(str(tmp_path / f"vectors-{namespace}.db")),
            sparse=sparse_indexes.setdefault(namespace, SparseBM25Index()),
            graph=GraphStore(str(tmp_path / "graph.db")),
            embedder=EmbeddingManager({}),  # 降级: 纯稀疏, 不触发向量库
            reranker=None,
        )

    return factory, metadata_store


async def _build_env(tmp_path: Path):
    """单 Agent + 真实记忆 + FakeChannel 的 E2E 夹具。"""
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    provider_manager.register(FakeLLMProvider(scripted_replies=[make_final_reply("好的, 记住了")]))
    memory_factory, metadata_store = _make_memory_factory(tmp_path)
    await metadata_store.init_schema()

    services: dict[str, Any] = {
        "global_config": {},
        "provider_manager": provider_manager,
        "memory_factory": memory_factory,
        "metrics": metrics,
    }
    agent_manager = AgentManager(services)
    await agent_manager.create(AgentConfig(agent_id="a", display_name="A"))
    await agent_manager.start("a")

    router = MessageRouter(
        RoutingRules(default_agents={"fake": "a"}), agents_provider=agent_manager.routing_infos
    )
    channel_registry = ChannelRegistry()
    channel_registry.register(FakeChannel())
    user_mapper = UserMapper(str(tmp_path / "identity.db"))
    return agent_manager, router, channel_registry, user_mapper, metadata_store, memory_factory


def _msg(content: str, *, user_id: str = "u1") -> ISACMessage:
    return ISACMessage(
        msg_id=f"m-{abs(hash(content)) % 100000}",
        platform="fake",
        timestamp=1,
        user_id=user_id,
        user_name=user_id,
        group_id=None,
        content=content,
        segments=[MessageSegment(type="text", data={"text": content})],
    )


async def _chat(am, router, cr, um, text: str) -> None:
    await process_message(
        _msg(text),
        event_bus=EventBus(),
        router=router,
        session_mgr=SessionManager({}),
        user_mapper=um,
        agent_manager=am,
        channel_registry=cr,
        metrics=get_default_metrics(),
    )
    # Q1 记忆写入是后台任务, gather 在途任务等它落盘
    pending = list(am._memory_tasks)  # noqa: SLF001
    if pending:
        await asyncio.gather(*pending)


@pytest.mark.asyncio
async def test_chat_writes_episode_and_survives_restart(tmp_path: Path) -> None:
    """聊天 → episodic 写入 → 模拟重启 (新 pipeline 预热) → BM25 检索命中。"""
    am, router, cr, um, metadata_store, _factory = await _build_env(tmp_path)

    await _chat(am, router, cr, um, "记住我最喜欢的项目代号是 zephyr_hiking_plan")

    # 直接检索 (同进程): 用户话与回复都在同一条 episode 里
    rows = await metadata_store.search_fts("a", "zephyr_hiking_plan")
    assert len(rows) == 1
    assert "zephyr_hiking_plan" in rows[0]["content"]
    assert "好的, 记住了" in rows[0]["content"]  # 回复也入库

    # 模拟重启: 全新 pipeline (空 BM25 内存索引) → warm_up 从 SQLite 重建 → 稀疏检索命中
    fresh_factory, _ = _make_memory_factory(tmp_path)
    fresh_pipeline = fresh_factory("a")
    loaded = await fresh_pipeline.warm_up_sparse_index()
    assert loaded == 1
    # N5b 批次E 项1: episode.user_id 现写归一 master_id (user_mapper 生成), 检索需用
    # 同一 master_id (与生产 heuristic 注入器口径一致), 不再用平台 id "u1"。
    profile = await um.resolve("fake", "u1")
    hits = await fresh_pipeline.search("zephyr_hiking_plan", top_k=3, user_id=profile.user_id)
    assert hits and "zephyr_hiking_plan" in hits[0].content


@pytest.mark.asyncio
async def test_profile_deepens_with_interactions(tmp_path: Path) -> None:
    """画像随互动加深: interaction_count 递增, relationship_depth 线性累积。"""
    am, router, cr, um, metadata_store, _factory = await _build_env(tmp_path)

    await _chat(am, router, cr, um, "第一句 alpha_token")
    await _chat(am, router, cr, um, "第二句 beta_token")

    profile = await um.resolve("fake", "u1")  # 已存在, 取 master_id
    stored = await metadata_store.get_person_profile("a", profile.user_id)
    assert stored is not None
    assert stored["interaction_count"] == 2
    assert stored["relationship_depth"] == pytest.approx(0.02)
    assert stored["name"] == "u1"


@pytest.mark.asyncio
async def test_user_mapper_persists_master_id_across_restart(tmp_path: Path) -> None:
    """UserMapper SQLite 持久化: 重启后同平台账号 → 同一 master_id (person_id 稳定)。"""
    db = str(tmp_path / "identity.db")
    first = UserMapper(db)
    profile_1 = await first.resolve("qq", "10001", "小明")

    reborn = UserMapper(db)  # 模拟重启: 全新实例, 仅共享 DB
    profile_2 = await reborn.resolve("qq", "10001")
    assert profile_2.user_id == profile_1.user_id
    assert profile_2.nickname == "小明"  # 昵称随画像恢复
    assert profile_2.first_seen == profile_1.first_seen

    # 不同账号仍是新身份
    other = await reborn.resolve("qq", "10002")
    assert other.user_id != profile_1.user_id


@pytest.mark.asyncio
async def test_user_mapper_without_db_stays_in_memory(tmp_path: Path) -> None:
    """不传 db_path 保持纯内存 (旧调用方/测试零行为变化): 重启即新身份。"""
    first = UserMapper()
    profile_1 = await first.resolve("qq", "10001")
    reborn = UserMapper()
    profile_2 = await reborn.resolve("qq", "10001")
    assert profile_2.user_id != profile_1.user_id
