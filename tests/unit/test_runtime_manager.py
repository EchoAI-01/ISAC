"""AgentManager.handle_message() 会话级状态隔离测试 (CODE_REVIEW_REPORT.md #6)。

修复前 GatingSystem 只持有单例 TurnScheduler/IdleBackoffController, 被同一 Agent
服务的所有会话共享；本测试交错调用两个不同 session 的 handle_message(), 验证
它们各自的话轮频率状态互不污染。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from isac.agent.loop import AgentResult
from isac.channel.model import ISACMessage, MessageSegment
from isac.core.types import ProgressEvent
from isac.gateway.models import Session
from isac.memory.pipeline import NoOpMemoryPipeline
from isac.provider.llm.stub import StubProvider
from isac.provider.manager import ProviderManager
from isac.runtime.config import AgentConfig
from isac.runtime.manager import AgentManager
from tests.fixtures.fakes import FakeLLMProvider, make_final_reply, make_tool_call_response

AGENT_ID = "agent_a"


async def _make_running_agent_manager() -> AgentManager:
    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    manager = AgentManager(
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        }
    )
    await manager.create(AgentConfig(agent_id=AGENT_ID))
    await manager.start(AGENT_ID)
    return manager


async def _make_running_agent_manager_with_provider(provider: object) -> AgentManager:
    provider_manager = ProviderManager({})
    provider_manager.register(provider)  # type: ignore[arg-type]
    manager = AgentManager(
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        }
    )
    await manager.create(AgentConfig(agent_id=AGENT_ID))
    await manager.start(AGENT_ID)
    return manager


def _at_message(msg_id: str, user_id: str) -> ISACMessage:
    """带 @ 分段的消息, 强制门控直接 TRIGGER, 不依赖 reply_necessity 评分的不确定性。"""
    return ISACMessage(
        msg_id=msg_id,
        platform="webchat",
        timestamp=0,
        user_id=user_id,
        user_name=user_id,
        content="你好",
        segments=[MessageSegment(type="at", data={})],
    )


@pytest.mark.asyncio
async def test_interleaved_sessions_have_independent_turn_scheduler_state() -> None:
    manager = await _make_running_agent_manager()
    session_a = Session(session_id="sess_a", user_id="u_a", agent_id=AGENT_ID)
    session_b = Session(session_id="sess_b", user_id="u_b", agent_id=AGENT_ID)

    # session_a 与 session_b 交错调用, session_a 交互轮次远多于 session_b。
    for i in range(10):
        await manager.handle_message(AGENT_ID, _at_message(f"a{i}", "u_a"), session_a, None)
        if i == 0:
            await manager.handle_message(AGENT_ID, _at_message("b0", "u_b"), session_b, None)

    instance = await manager.get(AGENT_ID)
    assert instance is not None
    scheduler_a = instance.gating.get_turn_scheduler(session_a.session_id)
    scheduler_b = instance.gating.get_turn_scheduler(session_b.session_id)

    assert scheduler_a is not scheduler_b
    # session_a: 10 轮, 每轮 1 条用户消息 + 1 条 Bot 回复 (StubProvider 总是非空回复);
    # recent_window_messages 统计窗口内全部事件 (含 Bot 自己的回复), 故为 2 * 轮数。
    assert scheduler_a.recent_window_messages == 20
    assert scheduler_a.recent_self_replies == 10
    # session_b 只交互了 1 轮, 不应被 session_a 后续 9 轮历史污染。
    assert scheduler_b.recent_window_messages == 2
    assert scheduler_b.recent_self_replies == 1


@pytest.mark.asyncio
async def test_interleaved_sessions_have_independent_idle_backoff_instances() -> None:
    manager = await _make_running_agent_manager()
    session_a = Session(session_id="sess_a", user_id="u_a", agent_id=AGENT_ID)
    session_b = Session(session_id="sess_b", user_id="u_b", agent_id=AGENT_ID)

    await manager.handle_message(AGENT_ID, _at_message("a0", "u_a"), session_a, None)
    await manager.handle_message(AGENT_ID, _at_message("b0", "u_b"), session_b, None)

    instance = await manager.get(AGENT_ID)
    assert instance is not None
    backoff_a = instance.gating.get_idle_backoff(session_a.session_id)
    backoff_b = instance.gating.get_idle_backoff(session_b.session_id)

    assert backoff_a is not backoff_b


@pytest.mark.asyncio
async def test_agent_lifecycle_records_metrics() -> None:
    """create/start/stop/destroy 应记录对应指标并维护 isac_agents_active 门数

    (CODE_REVIEW_REPORT.md #5)。
    """
    from isac.observability import get_default_metrics

    metrics = get_default_metrics()
    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    manager = AgentManager(
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
            "metrics": metrics,
        }
    )

    await manager.create(AgentConfig(agent_id="agent_x"))
    assert metrics.counter("isac_agent_creates_total").value() == 1

    await manager.start("agent_x")
    assert metrics.counter("isac_agent_starts_total").value() == 1
    assert metrics.gauge("isac_agents_active").value() == 1

    await manager.stop("agent_x")
    assert metrics.counter("isac_agent_stops_total").value() == 1
    assert metrics.gauge("isac_agents_active").value() == 0

    await manager.start("agent_x")
    assert metrics.gauge("isac_agents_active").value() == 1
    await manager.destroy("agent_x")
    assert metrics.gauge("isac_agents_active").value() == 0


@pytest.mark.asyncio
async def test_load_persisted_agents_restores_enabled_agents(tmp_path) -> None:
    """重启恢复: data/agents/<id>/config.jsonc 的 enabled=true Agent 自动 create+start
    (CODE_REVIEW_REPORT.md #2)。"""
    from isac.runtime.config import save_agent_config
    from isac.runtime.manager import load_persisted_agents

    agents_dir = tmp_path / "agents"
    # 写两个 Agent: a 启用, b 禁用
    save_agent_config(agents_dir / "a" / "config.jsonc", AgentConfig(agent_id="a", display_name="A"))
    save_agent_config(
        agents_dir / "b" / "config.jsonc",
        AgentConfig(agent_id="b", display_name="B", enabled=False),
    )

    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    manager = AgentManager(
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        }
    )

    report = await load_persisted_agents(manager, str(agents_dir))

    assert report["a"] == "running"
    assert report["b"] == "stopped"
    inst_a = await manager.get("a")
    inst_b = await manager.get("b")
    assert inst_a is not None and inst_a.status == "running"
    assert inst_b is not None and inst_b.status == "stopped"


@pytest.mark.asyncio
async def test_load_persisted_agents_skips_invalid_config(tmp_path) -> None:
    """损坏的 config.jsonc 不阻塞其他 Agent 恢复 (CODE_REVIEW_REPORT.md #2)。"""
    from isac.runtime.manager import load_persisted_agents

    agents_dir = tmp_path / "agents"
    (agents_dir / "broken" / "config.jsonc").parent.mkdir(parents=True, exist_ok=True)
    (agents_dir / "broken" / "config.jsonc").write_text("{not valid json", encoding="utf-8")

    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    manager = AgentManager(
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        }
    )

    report = await load_persisted_agents(manager, str(agents_dir))

    assert report["broken"].startswith("failed:")
    # 没有任何 Agent 被加载到内存
    assert await manager.list_ids() == []


@pytest.mark.asyncio
async def test_load_persisted_agents_missing_dir_returns_empty(tmp_path) -> None:
    """目录不存在时返回空报告, 不抛异常。"""
    from isac.runtime.manager import load_persisted_agents

    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    manager = AgentManager(
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        }
    )

    report = await load_persisted_agents(manager, str(tmp_path / "nonexistent"))
    assert report == {}


# ── Fix-26: destroy(keep_memory=False) 真实清理 vector/graph (R7 此前零测试覆盖) ──


async def _make_memory_backed_manager(tmp_path):
    """真实 MetadataStore + 按 namespace 惰性创建的 VectorStore + 共享 GraphStore,
    services 里同时注入 vector_resolver/graph_store (与 main.py build_services 的
    生产接线一致), 才能真正走到 _purge_vector_and_graph 里的两条清理路径
    (此前全仓无任何测试这样接线过, keep_memory=False 从未被真实测试触发)。"""
    from isac.memory.embedder import EmbeddingManager
    from isac.memory.pipeline import MemoryRetrievalPipeline
    from isac.memory.storage.graph import GraphStore
    from isac.memory.storage.metadata import MetadataStore
    from isac.memory.storage.sparse import SparseBM25Index
    from isac.memory.storage.vector import VectorStore

    metadata_store = MetadataStore(str(tmp_path / "metadata.db"))
    await metadata_store.init_schema()
    graph_store = GraphStore(str(tmp_path / "graph.db"))
    vector_stores: dict[str, VectorStore] = {}
    sparse_indexes: dict[str, SparseBM25Index] = {}

    def _vector_store_for(namespace: str) -> VectorStore:
        store = vector_stores.get(namespace)
        if store is None:
            store = VectorStore(str(tmp_path / f"vectors-{namespace}.db"), dimension=4)
            vector_stores[namespace] = store
        return store

    def memory_factory(namespace: str) -> MemoryRetrievalPipeline:
        return MemoryRetrievalPipeline(
            namespace=namespace,
            metadata=metadata_store,
            vector=_vector_store_for(namespace),
            sparse=sparse_indexes.setdefault(namespace, SparseBM25Index()),
            graph=graph_store,
            embedder=EmbeddingManager({}),  # 降级纯稀疏, 不会真的触发 embedding API
            reranker=None,
        )

    manager = AgentManager(
        {
            "provider_manager": ProviderManager({}),
            "memory_factory": memory_factory,
            "global_config": {},
            "vector_resolver": _vector_store_for,
            "graph_store": graph_store,
        }
    )
    manager._services["provider_manager"].register(StubProvider())  # noqa: SLF001
    await manager.create(AgentConfig(agent_id=AGENT_ID))
    await manager.start(AGENT_ID)
    return manager, metadata_store, vector_stores, graph_store


@pytest.mark.asyncio
async def test_destroy_keep_memory_false_purges_vector_file_and_graph_edges(tmp_path) -> None:
    """Fix-26 (R7 补测): destroy(keep_memory=False) 应真正删除该 namespace 的
    vector DB 文件、清空 graph edges、清空 metadata episodes——之前这条路径
    (_purge_vector_and_graph) 在 1442 个单测里零覆盖。"""
    manager, metadata_store, vector_stores, graph_store = await _make_memory_backed_manager(tmp_path)
    instance = await manager.get(AGENT_ID)
    namespace = instance.memory.namespace

    # 直接写一条 episode + 一条向量 + 一条 graph edge, 模拟"已经聊过一段时间"
    await metadata_store.store_episode(
        namespace, {"session_id": "s1", "user_id": "u1", "group_id": "", "content": "hello"}
    )
    vector = vector_stores[namespace]
    await vector.upsert("fake-memory-id", [1.0, 0.0, 0.0, 0.0])
    await graph_store.add_edge(namespace, "user:u1", "member_of", "group:g1")
    db_path = vector.db_path
    assert await asyncio.to_thread(Path(db_path).exists)

    await manager.destroy(AGENT_ID, keep_memory=False)

    assert not await asyncio.to_thread(Path(db_path).exists)  # vector DB 文件已删除
    assert await graph_store.neighbors(namespace, "user:u1") == []  # graph edges 已清空
    assert await metadata_store.iter_episodes_by_namespace(namespace) == []  # episodes 已清空


@pytest.mark.asyncio
async def test_destroy_keep_memory_true_does_not_purge(tmp_path) -> None:
    """对照: keep_memory=True (默认) 时不应触碰 vector/graph/metadata 数据。"""
    manager, metadata_store, vector_stores, graph_store = await _make_memory_backed_manager(tmp_path)
    instance = await manager.get(AGENT_ID)
    namespace = instance.memory.namespace
    vector = vector_stores[namespace]
    await vector.upsert("fake-memory-id", [1.0, 0.0, 0.0, 0.0])
    db_path = vector.db_path

    await manager.destroy(AGENT_ID, keep_memory=True)

    assert await asyncio.to_thread(Path(db_path).exists)  # 未被清理


@pytest.mark.asyncio
async def test_destroy_keep_memory_false_waits_for_in_flight_memory_write(tmp_path) -> None:
    """Fix-26: destroy(keep_memory=False) 清理前必须等该 Agent 在途的记忆写入
    任务结束, 不能让 purge 与仍在跑的 store_episode 交错。用 _schedule_memory_write
    模拟"回复刚产出, 后台写入还没完成"再立即 destroy, 断言 destroy() 返回时
    该任务一定已经 done (证明确实等过, 不是碰巧先完成)。"""
    from isac.channel.model import ISACMessage
    from isac.gateway.models import Session

    manager, metadata_store, vector_stores, graph_store = await _make_memory_backed_manager(tmp_path)
    instance = await manager.get(AGENT_ID)
    session = Session(session_id="s1", user_id="u1", platform="webchat")
    message = ISACMessage(
        msg_id="m1", platform="webchat", timestamp=0, user_id="u1", user_name="u1", content="你好",
    )
    manager._schedule_memory_write(instance, message, session, None, "回复内容")  # noqa: SLF001
    scheduled_task = next(iter(manager._memory_tasks))  # noqa: SLF001

    await manager.destroy(AGENT_ID, keep_memory=False)

    assert scheduled_task.done()  # destroy() 必须等它完成才能返回


@pytest.mark.asyncio
async def test_handle_message_wires_progress_reporter_and_reuses_per_session() -> None:
    """D9-1: handle_message() 消费 instance.services["progress_reporter_factory"]
    构造/复用 per-session ProgressReporter, 绑定传入的 progress_sender, 赋值
    agent_context.report_progress, 且正确填充 agent_id (此前恒为空字符串)。

    同一 session 两次调用应复用同一个 ProgressReporter 实例 (per-session, 非
    per-message), 使 min_interval_seconds 频控能跨消息生效。
    """
    provider = FakeLLMProvider(
        scripted_replies=[
            make_tool_call_response("query_memory", arguments={"query": "hi"}),
            make_final_reply("first done"),
            make_tool_call_response("query_memory", arguments={"query": "again"}),
            make_final_reply("second done"),
        ]
    )
    manager = await _make_running_agent_manager_with_provider(provider)
    session = Session(session_id="sess_p1", user_id="u_p1", agent_id=AGENT_ID)

    captured: list[ProgressEvent] = []

    async def sender(text: str, event: ProgressEvent) -> None:
        captured.append(event)

    await manager.handle_message(
        AGENT_ID, _at_message("m1", "u_p1"), session, None, progress_sender=sender
    )
    await manager.handle_message(
        AGENT_ID, _at_message("m2", "u_p1"), session, None, progress_sender=sender
    )

    planned_events = [e for e in captured if e.stage == "planned"]
    # message2 的 planned 被跨消息的 min_interval_seconds (默认 2.0s) 频控吞掉
    # (message1 的 completed 刚更新过 _last_emit_at); 这恰恰证明两次 handle_message
    # 复用的是同一个 ProgressReporter, 而非各自新建、频控互不干扰的实例——若是
    # per-message 新建, 两条 planned 都会因 _last_emit_at 重置为 0 而通过。
    assert len(planned_events) == 1
    assert planned_events[0].agent_id == AGENT_ID
    assert planned_events[0].session_id == "sess_p1"


@pytest.mark.asyncio
async def test_handle_message_passes_configured_slow_tool_policy_to_context() -> None:
    """D9-7: services 里的慢工具阈值/开关应来自 Agent 配置的 ProgressPolicy,
    而不是 loop.py 内部硬编码的默认值 (此前是死配置)。"""
    manager = await _make_running_agent_manager()
    instance = await manager.get(AGENT_ID)
    assert instance is not None

    captured_services: list[dict] = []

    class _CapturingLoop:
        async def run(self, messages, context):
            captured_services.append(context.services)
            return AgentResult(content="done")

    instance.loop = _CapturingLoop()  # type: ignore[assignment]
    instance.config.persona = {
        "progress": {"slow_tool_threshold_seconds": 0.5, "report_before_slow_tool": False}
    }

    session = Session(session_id="sess_policy", user_id="u1", agent_id=AGENT_ID)
    await manager.handle_message(AGENT_ID, _at_message("m1", "u1"), session, None)

    assert len(captured_services) == 1
    assert captured_services[0]["progress_slow_tool_threshold_seconds"] == 0.5
    assert captured_services[0]["progress_report_before_slow_tool"] is False

    instance = await manager.get(AGENT_ID)
    assert instance is not None
    assert len(instance.progress_reporters) == 1
