"""P5 企业化激活集成测试 (R7-③)。

端到端验证三大企业特性:
1. 跨租户不可见: 两租户的 MemoryRetrievalPipeline 共享 DB 文件, TenantIsolationGuard
   enabled 时, A 写入的 episode 经 B 的 pipeline.search 检索不可见 (pipeline 层端到端,
   区别于 MetadataStore 层单元测试)。
2. 插件进程隔离: PluginIsolationHost (spawn 子进程) 真实加载插件 + 调用方法 +
   _on_crash 崩溃重启 (达 max 后放弃)。
3. Workflow 声明式执行: load_workflows_from_dir 从 JSON 加载 → start 推进 →
   SUCCEEDED + 持久化文件落地 (可观测); tool: 前缀 action 经 build_default_action_handler
   真实经 agent_manager 取 ToolRegistry.execute 执行。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from isac.agent.tools.base import Tool, ToolContext, ToolPermission, ToolResult
from isac.agent.tools.registry import ToolRegistry
from isac.memory.embedder import EmbeddingManager
from isac.memory.model import MemoryGovernor
from isac.memory.pipeline import MemoryRetrievalPipeline
from isac.memory.reranker import Reranker
from isac.memory.storage.graph import GraphStore
from isac.memory.storage.metadata import MetadataStore
from isac.memory.storage.sparse import SparseBM25Index
from isac.memory.storage.vector import VectorStore
from isac.plugin.isolation.host import PluginIsolationHost
from isac.plugin.isolation.protocol import IPCEnvelope
from isac.runtime.tenancy.isolation import TenantIsolationGuard
from isac.runtime.tenancy.models import TenantContext
from isac.runtime.workflow.actions import build_default_action_handler
from isac.runtime.workflow.engine import WorkflowEngine
from isac.runtime.workflow.loader import load_workflows_from_dir
from isac.runtime.workflow.models import WorkflowStatus

NAMESPACE = "agent_p5"


# ── 1. 跨租户不可见 (pipeline 层端到端) ─────────────────────────


async def _make_tenanted_pipeline(
    tmp_path: Path, tenant: TenantContext, guard: TenantIsolationGuard,
) -> MemoryRetrievalPipeline:
    """构造带租户隔离的 pipeline (同 DB 文件, 不同 tenant_context)。"""
    metadata = MetadataStore(
        str(tmp_path / "memory.db"), tenant_guard=guard, tenant_context=tenant,
    )
    await metadata.init_schema()
    return MemoryRetrievalPipeline(
        namespace=NAMESPACE,
        metadata=metadata,
        vector=VectorStore(str(tmp_path / "vectors.db"), dimension=3),
        sparse=SparseBM25Index(),
        graph=GraphStore(str(tmp_path / "graph.db")),
        embedder=EmbeddingManager({}),
        reranker=Reranker({}),
        enable_graph_recall=False,
    )


@pytest.mark.asyncio
async def test_cross_tenant_search_isolated(tmp_path: Path) -> None:
    """两租户 pipeline 共享 DB: A 写入的 episode 经 B 的 pipeline.search 不可见。"""
    guard = TenantIsolationGuard(enabled=True)
    tenant_a = TenantContext(organization_id="acme", tenant_id="t1")
    tenant_b = TenantContext(organization_id="globex", tenant_id="t9")
    pipe_a = await _make_tenanted_pipeline(tmp_path, tenant_a, guard)
    pipe_b = await _make_tenanted_pipeline(tmp_path, tenant_b, guard)
    try:
        mid = await pipe_a.store_episode("租户A 的 机密 记忆", "s1", user_id="u1", agent_id=NAMESPACE)
        assert mid
        # B 的 pipeline 经 metadata.search_fts (租户谓词注入) 不可见
        hits_b = await pipe_b.search("机密", top_k=10, user_id="u1", agent_id=NAMESPACE)
        assert all(h.id != mid for h in hits_b), "租户 B 不应检索到租户 A 的记忆"
        # A 自己可见
        hits_a = await pipe_a.search("机密", top_k=10, user_id="u1", agent_id=NAMESPACE)
        assert any(h.id == mid for h in hits_a), "租户 A 应能检索到自己的记忆"
    finally:
        await pipe_a.vector.close()
        await pipe_a.graph.close()
        await pipe_b.vector.close()
        await pipe_b.graph.close()


@pytest.mark.asyncio
async def test_cross_tenant_governance_rejected(tmp_path: Path) -> None:
    """U0 Fix-85: 两租户共享同一 memory.db, 治理面 (freeze/protect/correct/delete/
    restore/export) 必须按租户作用域隔离 —— 租户 A 的 governor 对租户 B 的记忆条目
    一律拒绝 (返回 False / 空), 租户 B 自己的 governor 可正常操作。

    回归此前漏洞: MemoryGovernor 直连 db_path 裸 SQL 只按 agent_id 过滤, 绕过租户
    谓词, 租户 A 凭据可 freeze/correct/delete 租户 B 的记忆 (多租户卖点面越权)。
    """
    guard = TenantIsolationGuard(enabled=True)
    tenant_a = TenantContext(organization_id="acme", tenant_id="t1")
    tenant_b = TenantContext(organization_id="globex", tenant_id="t9")
    db_path = str(tmp_path / "memory.db")
    store_a = MetadataStore(db_path, tenant_guard=guard, tenant_context=tenant_a)
    store_b = MetadataStore(db_path, tenant_guard=guard, tenant_context=tenant_b)
    await store_b.init_schema()
    # 租户 B 写入一条记忆 (打 globex/t9 租户标)
    item_id = await store_b.store_episode(
        NAMESPACE, {"id": "ep_b_secret", "content": "租户B 的机密记忆", "summary": "s"}
    )
    assert item_id == "ep_b_secret"

    # 租户 A 的 governor (包装带 acme/t1 上下文的 store) 越权操作 → 一律拒绝
    gov_a = MemoryGovernor(store_a)
    assert await gov_a.freeze(item_id, NAMESPACE) is False
    assert await gov_a.protect(item_id, NAMESPACE) is False
    assert await gov_a.correct(item_id, "被篡改", NAMESPACE) is False
    assert await gov_a.delete(item_id, NAMESPACE) is False
    assert await gov_a.restore(item_id, NAMESPACE) is False
    assert await gov_a.export(NAMESPACE) == []

    # 正向对照: 租户 B 自己的 governor 可操作 (同库同租户不误伤)
    gov_b = MemoryGovernor(store_b)
    assert await gov_b.freeze(item_id, NAMESPACE) is True
    assert await gov_b.export(NAMESPACE) != []


@pytest.mark.asyncio
async def test_governance_default_tenant_passthrough(tmp_path: Path) -> None:
    """U0 Fix-85 回归保护: tenancy 未启用 (guard disabled) 时治理行为零变化 ——
    不加租户谓词, 既有单租户部署不受影响。"""
    store = MetadataStore(str(tmp_path / "memory.db"))  # 无 guard/context
    await store.init_schema()
    item_id = await store.store_episode(NAMESPACE, {"id": "ep_1", "content": "普通记忆"})
    gov = MemoryGovernor(store)
    assert await gov.freeze(item_id, NAMESPACE) is True
    assert await gov.delete(item_id, NAMESPACE) is True


# ── 1b. U4 租户机制强制 (画像/行话/工具召回/键统一 全场景) ──────


@pytest.mark.asyncio
async def test_u4_cross_tenant_profiles_jargon_meta_isolated(tmp_path: Path) -> None:
    """U4 两租户共库全场景零串档: 画像/行话/episode 元数据读取跨租户不可见。"""
    guard = TenantIsolationGuard(enabled=True)
    tenant_a = TenantContext(organization_id="acme", tenant_id="t1")
    tenant_b = TenantContext(organization_id="globex", tenant_id="t9")
    db_path = str(tmp_path / "memory.db")
    store_a = MetadataStore(db_path, tenant_guard=guard, tenant_context=tenant_a)
    store_b = MetadataStore(db_path, tenant_guard=guard, tenant_context=tenant_b)
    await store_a.init_schema()

    ns_a = guard.namespace_for(NAMESPACE, tenant_a)  # acme:t1:agent_p5
    # 租户 A 写画像 + 行话 + episode
    await store_a.upsert_person_profile(ns_a, {"person_id": "u1", "name": "张三"})
    await store_a.upsert_jargon(ns_a, "中台", "共享服务平台")
    ep_id = await store_a.store_episode(ns_a, {"content": "租户A 机密", "user_id": "u1", "session_id": "s1"})

    # 租户 B 全场景不可见 (即使知道 A 的命名空间键)
    assert await store_b.get_person_profile(ns_a, "u1") is None
    assert await store_b.list_jargon(ns_a) == []
    assert await store_b.get_episode_meta_by_ids([ep_id]) == []
    # A 自己可见
    assert (await store_a.get_person_profile(ns_a, "u1"))["name"] == "张三"
    assert [j["word"] for j in await store_a.list_jargon(ns_a)] == ["中台"]
    assert (await store_a.get_episode_meta_by_ids([ep_id]))[0]["id"] == ep_id


@pytest.mark.asyncio
async def test_u4_key_unification_write_read_consistent(tmp_path: Path) -> None:
    """U4 键统一: 写侧 (manager/consolidator 口径 = pipeline.namespace) 与读侧
    (注入器口径) 同键, tenancy 开启时画像可读; 跨租户同键不可见。

    生产 memory_factory 对 namespace 加租户前缀 (namespace_for), pipeline.namespace
    即前缀键 —— 此处直接按前缀键构造 pipeline 模拟该口径。
    """
    guard = TenantIsolationGuard(enabled=True)
    tenant_a = TenantContext(organization_id="acme", tenant_id="t1")
    tenant_b = TenantContext(organization_id="globex", tenant_id="t9")
    ns_a = guard.namespace_for(NAMESPACE, tenant_a)
    ns_b = guard.namespace_for(NAMESPACE, tenant_b)

    async def _pipeline_for(tenant: TenantContext, ns: str) -> MemoryRetrievalPipeline:
        metadata = MetadataStore(
            str(tmp_path / "memory.db"), tenant_guard=guard, tenant_context=tenant,
        )
        await metadata.init_schema()
        return MemoryRetrievalPipeline(
            namespace=ns,
            metadata=metadata,
            vector=VectorStore(str(tmp_path / "vectors.db"), dimension=3),
            sparse=SparseBM25Index(),
            graph=GraphStore(str(tmp_path / "graph.db")),
            embedder=EmbeddingManager({}),
            reranker=Reranker({}),
            enable_graph_recall=False,
        )

    pipe_a = await _pipeline_for(tenant_a, ns_a)
    pipe_b = await _pipeline_for(tenant_b, ns_b)
    try:
        # 写侧 (manager 口径): pipeline.namespace 键
        await pipe_a.metadata.upsert_person_profile(
            pipe_a.namespace, {"person_id": "master_u1", "name": "张三", "profile_text": "A 的画像"},
        )
        # 读侧 (注入器口径): 同一 pipeline.namespace 键可读
        profile = await pipe_a.metadata.get_person_profile(pipe_a.namespace, "master_u1")
        assert profile is not None and profile["name"] == "张三"
        # 租户 B 用自己的前缀键读不到 A 的画像; 即使拿到 A 的键也被谓词拦
        assert await pipe_b.metadata.get_person_profile(pipe_b.namespace, "master_u1") is None
        assert await pipe_b.metadata.get_person_profile(pipe_a.namespace, "master_u1") is None
    finally:
        await pipe_a.vector.close()
        await pipe_a.graph.close()
        await pipe_b.vector.close()
        await pipe_b.graph.close()


@pytest.mark.asyncio
async def test_u4_tool_recall_master_id(tmp_path: Path) -> None:
    """U4 QueryMemoryTool master_id 修复的场景回归: episode 按 master_id 落盘,
    私聊检索必须用 master_id 才命中 (平台 id 检索系统性漏)。"""
    guard = TenantIsolationGuard(enabled=True)
    tenant_a = TenantContext(organization_id="acme", tenant_id="t1")
    pipe = await _make_tenanted_pipeline(tmp_path, tenant_a, guard)
    try:
        # 写入侧口径 (manager._write_memory): user_id = master_id
        mid = await pipe.store_episode("项目 进度 汇报", "s1", user_id="master_u1", agent_id=NAMESPACE)
        assert mid
        # 工具修复后口径: user_profile.user_id (master_id) → 命中
        hits = await pipe.search("进度", top_k=5, user_id="master_u1", agent_id=NAMESPACE)
        assert any(h.id == mid for h in hits)
        # 修复前的错误口径: 平台 id 私聊检索 → 漏 (group_id 为空按私聊过滤)
        hits_platform = await pipe.search("进度", top_k=5, user_id="platform_u1", agent_id=NAMESPACE)
        assert all(h.id != mid for h in hits_platform)
    finally:
        await pipe.vector.close()
        await pipe.graph.close()


# ── 2. 插件进程隔离 (spawn → load → call → crash restart) ─────────


def _write_echo_plugin(plugin_dir: Path) -> None:
    """写一个最小 ISACPlugin (echo 桩) 供隔离子进程加载。"""
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "manifest.jsonc").write_text(
        '{"name": "p5_echo", "version": "0.1.0", "entry": "plugin.py"}', encoding="utf-8"
    )
    (plugin_dir / "plugin.py").write_text(
        "from isac.plugin.native.plugin import ISACPlugin\n"
        "\n"
        "class P5EchoPlugin(ISACPlugin):\n"
        "    def ping(self):\n"
        "        return 'pong'\n"
        "\n"
        "    async def greet(self, name):\n"
        "        return f'hi {name}'\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_plugin_isolation_load_and_call(tmp_path: Path) -> None:
    """隔离子进程真实加载插件 + 调用同步/异步方法 + 私有方法被拒。"""
    plugin_dir = tmp_path / "p5_echo"
    _write_echo_plugin(plugin_dir)
    host = PluginIsolationHost("p5_echo")
    await host.spawn()
    try:
        loaded = await host.load_plugin(str(plugin_dir))
        assert loaded.kind == "result"
        assert loaded.payload["loaded"] == "p5_echo"
        # 同步方法
        sync_res = await host.call(IPCEnvelope(kind="call", plugin_id="p5_echo", payload={"method": "ping"}))
        assert sync_res.kind == "result"
        assert sync_res.payload["result"] == "pong"
        # 异步方法
        async_res = await host.call(IPCEnvelope(
            kind="call", plugin_id="p5_echo", payload={"method": "greet", "args": {"name": "isac"}}
        ))
        assert async_res.kind == "result"
        assert async_res.payload["result"] == "hi isac"
        # 私有方法被拒
        denied = await host.call(IPCEnvelope(kind="call", plugin_id="p5_echo", payload={"method": "_secret"}))
        assert denied.kind == "error"
    finally:
        await host.kill()


@pytest.mark.asyncio
async def test_plugin_isolation_crash_restart_and_give_up() -> None:
    """_on_crash 崩溃重启: max_restart_attempts 内 respawn, 超限后放弃 (is_alive=False)。

    _on_crash 语义: 先判 ``_restart_count >= max`` → 放弃 (不递增); 否则递增并 respawn。
    max=1: 第 1 次崩溃 count 0<1 → respawn(count=1, alive); 第 2 次崩溃 count 1>=1 → 放弃(count 不变, is_alive=False)。
    """
    host = PluginIsolationHost("p5_crash", max_restart_attempts=1)
    await host.spawn()
    try:
        assert host.is_alive
        # 第一次崩溃: 未达 max → respawn, 仍 alive
        await host._on_crash()  # noqa: SLF001 — 注入崩溃, 验证重启逻辑
        assert host._restart_count == 1  # noqa: SLF001
        assert host.is_alive, "未超 max 应 respawn 仍 alive"
        # 第二次崩溃: 已达 max → 放弃 (不递增, is_alive=False)
        await host._on_crash()  # noqa: SLF001
        assert host._restart_count == 1  # noqa: SLF001 — 放弃路径不递增
        assert host.is_alive is False, "超过 max_restart_attempts 后应放弃 (is_alive=False)"
    finally:
        if host.is_alive:
            await host.kill()


# ── 3. Workflow 声明式执行 + tool: action ─────────────────────────


class _EchoTool(Tool):
    """最小工具: 回显参数 text, 记录被调用。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "回显文本 (测试用)"

    async def execute(self, context: ToolContext) -> ToolResult:
        self.calls.append(dict(context.args))
        return ToolResult(content=f"echo: {context.args.get('text', '')}")


class _FakeInstance:
    """最小 AgentInstance 桩: 仅含 tools (ToolRegistry) + services。"""

    def __init__(self, tools: ToolRegistry, services: dict[str, Any] | None = None) -> None:
        self.tools = tools
        self.services = services or {}


@pytest.mark.asyncio
async def test_workflow_declarative_load_and_execute(tmp_path: Path) -> None:
    """声明式加载: 写 workflow JSON → load_workflows_from_dir → start → SUCCEEDED + 持久化。"""
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    wf_def = {
        "workflow_id": "wf_p5",
        "name": "p5 流程",
        "stages": [
            {"stage_id": "s1", "action": "noop:step1", "params": {}},
            {"stage_id": "s2", "action": "noop:step2", "params": {}},
        ],
        "transitions": [
            {"from_stage": "s1", "to_stage": "s2", "kind": "SEQUENTIAL"},
        ],
    }
    (wf_dir / "wf_p5.json").write_text(json.dumps(wf_def, ensure_ascii=False), encoding="utf-8")
    engine = WorkflowEngine(base_dir=str(tmp_path / "state"))
    order: list[str] = []

    async def handler(stage: Any) -> None:
        order.append(str(getattr(stage, "stage_id", "")))

    engine.set_action_handler(handler)
    count = load_workflows_from_dir(engine, str(wf_dir))
    assert count == 1, "应加载 1 个 workflow JSON"
    status = await engine.start("wf_p5")
    assert status is WorkflowStatus.SUCCEEDED
    assert order == ["s1", "s2"], "两 stage 按声明顺序执行"
    # 可观测性: 持久化文件落地
    assert (tmp_path / "state" / "wf_p5.json").exists(), "workflow 状态应持久化到文件"


@pytest.mark.asyncio
async def test_workflow_tool_action_invokes_tool(tmp_path: Path) -> None:
    """tool: 前缀 action 经 build_default_action_handler 真实调 ToolRegistry.execute。

    验证生产 action_handler 调用链: stage.action="tool:echo" → params 取 agent_id →
    resolver 取 instance → tools.execute → 工具真实执行。
    """
    echo_tool = _EchoTool()
    registry = ToolRegistry(ToolPermission({"echo": "allow"}))
    registry.register(echo_tool)
    instance = _FakeInstance(tools=registry)

    # resolver: 直接 callable 形式 (await resolver(agent_id) → instance)
    async def resolver(agent_id: str) -> _FakeInstance:
        if agent_id == "a1":
            return instance
        return None  # type: ignore[return-value]

    engine = WorkflowEngine(base_dir=str(tmp_path / "state"))
    engine.set_action_handler(build_default_action_handler(resolver))
    from isac.runtime.workflow.models import Stage, Workflow

    wf = Workflow(
        workflow_id="wf_tool",
        stages=[Stage(stage_id="s1", action="tool:echo", params={"agent_id": "a1", "text": "hello"})],
        transitions=[],
    )
    engine.register(wf)
    status = await engine.start("wf_tool")
    assert status is WorkflowStatus.SUCCEEDED
    assert echo_tool.calls, "tool:echo action 应真实触发工具 execute"
    assert echo_tool.calls[0].get("text") == "hello"
