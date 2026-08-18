"""U4 租户机制强制专项测试 (TenantBoundDB + 四表租户列 + 裸 SQL 绕过审计)。

验收覆盖 (DEVELOPMENT_PLAN §四 U4):
- TenantBoundDB 原语 (scoped/predicate/row_values/active) 在 disabled/默认租户/
  启用三态下的行为;
- person_profiles/jargon_entries/memory_revisions/memory_audit 四表租户隔离
  (两租户共库零串档);
- get_episode_meta_by_ids 租户作用域 (consolidator 裸 SQL 绕过点的机制替代);
- delete_namespace 租户谓词双保险;
- 审计: 生产记忆域代码无裸 aiosqlite.connect 绕过点 (允许清单外零直连)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from isac.memory.storage.metadata import MetadataStore
from isac.memory.storage.tenant_bound import TenantBoundDB
from isac.runtime.tenancy.isolation import TenantIsolationGuard
from isac.runtime.tenancy.models import TenantContext


class _ProbeGuard:
    """最小 guard 替身 (仅 active 判定测试用, 不依赖真实 enforce)。"""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled


def test_tenant_bound_active_states() -> None:
    """active: guard 缺失/disabled/默认租户 → False; enabled+非默认租户 → True。"""
    ctx_t1 = TenantContext(organization_id="acme", tenant_id="t1")
    ctx_default = TenantContext()
    assert TenantBoundDB("x.db").active is False
    assert TenantBoundDB("x.db", tenant_guard=_ProbeGuard(False), tenant_context=ctx_t1).active is False
    assert TenantBoundDB("x.db", tenant_guard=_ProbeGuard(True), tenant_context=ctx_default).active is False
    assert TenantBoundDB("x.db", tenant_guard=_ProbeGuard(True), tenant_context=ctx_t1).active is True


def test_tenant_bound_primitives_passthrough_when_inactive() -> None:
    """未生效时三原语直通 (单租户零行为变化)。"""
    tdb = TenantBoundDB("x.db")
    q, p = tdb.scoped("SELECT * FROM episodes WHERE id = ?", ["e1"])
    assert q == "SELECT * FROM episodes WHERE id = ?" and p == ["e1"]
    assert tdb.predicate() == ("", [])
    assert tdb.row_values() == ("default", "default")


def test_tenant_bound_primitives_when_active() -> None:
    """生效时: scoped 包子查询, predicate 给规范片段, row_values 按 context 打标。"""
    guard = TenantIsolationGuard(enabled=True)
    ctx = TenantContext(organization_id="acme", tenant_id="t1")
    tdb = TenantBoundDB("x.db", tenant_guard=guard, tenant_context=ctx)

    q, p = tdb.scoped("SELECT * FROM episodes WHERE agent_id = ?", ["a1"])
    assert "_tenant_scoped" in q and p == ["a1", "acme", "t1"]

    frag, params = tdb.predicate()
    assert frag == " AND organization_id = ? AND tenant_id = ?"
    assert params == ["acme", "t1"]

    assert tdb.row_values() == ("acme", "t1")


# ── 四表租户隔离 (两租户共库) ────────────────────────────────


def _make_store(tmp_path: Path, org: str, tenant: str) -> MetadataStore:
    store = MetadataStore(
        str(tmp_path / "memory.db"),
        tenant_guard=TenantIsolationGuard(enabled=True),
        tenant_context=TenantContext(organization_id=org, tenant_id=tenant),
    )
    return store


@pytest.mark.asyncio
async def test_person_profiles_cross_tenant_isolated(tmp_path: Path) -> None:
    """两租户共库: 租户 A 的画像对租户 B 不可见 (写打标 + 读作用域)。

    键用生产口径的租户前缀命名空间 (memory_factory namespace_for 产物);
    租户 B 即使知道 A 的键名也读不到 (谓词在机制层拦截)。
    """
    store_a = _make_store(tmp_path, "acme", "t1")
    store_b = _make_store(tmp_path, "globex", "t2")
    await store_a.init_schema()

    key_a = "acme:t1:agent_x"
    await store_a.upsert_person_profile(key_a, {"person_id": "u1", "name": "张三", "profile_text": "A 的画像"})
    await store_a.increment_person_interaction(key_a, "u1", name="张三")

    profile_a = await store_a.get_person_profile(key_a, "u1")
    assert profile_a is not None and profile_a["name"] == "张三"
    # 租户 B 即使知道 A 的命名空间键也读不到 (租户谓词机制拦截)
    assert await store_b.get_person_profile(key_a, "u1") is None


@pytest.mark.asyncio
async def test_jargon_cross_tenant_isolated(tmp_path: Path) -> None:
    """两租户共库: 租户 A 的行话对租户 B 不可见。"""
    store_a = _make_store(tmp_path, "acme", "t1")
    store_b = _make_store(tmp_path, "globex", "t2")
    await store_a.init_schema()

    key_a = "acme:t1:agent_x"
    await store_a.upsert_jargon(key_a, "中台", "共享服务平台", "内部语境")
    jargon_a = await store_a.list_jargon(key_a)
    assert [j["word"] for j in jargon_a] == ["中台"]
    assert await store_b.list_jargon(key_a) == []


@pytest.mark.asyncio
async def test_delete_namespace_respects_tenant_predicate(tmp_path: Path) -> None:
    """delete_namespace 租户谓词双保险: 键前缀之外, 谓词机制再拦一道。

    构造极端场景: 手工把 A 的行写成与 B 请求相同的裸键 (绕过前缀), 验证
    B 的 delete_namespace 仍因租户谓词删不动 A 打的标。
    """
    store_a = _make_store(tmp_path, "acme", "t1")
    store_b = _make_store(tmp_path, "globex", "t2")
    await store_a.init_schema()

    await store_a.upsert_person_profile("shared_key", {"person_id": "u1", "name": "张三"})
    await store_a.upsert_jargon("shared_key", "黑话", "含义")
    removed = await store_b.delete_namespace("shared_key")
    assert removed == 0
    assert await store_a.get_person_profile("shared_key", "u1") is not None
    assert [j["word"] for j in await store_a.list_jargon("shared_key")] == ["黑话"]
    # A 自己删得动 (同租户谓词匹配)
    await store_a.delete_namespace("shared_key")
    assert await store_a.get_person_profile("shared_key", "u1") is None


@pytest.mark.asyncio
async def test_get_episode_meta_by_ids_tenant_scoped(tmp_path: Path) -> None:
    """get_episode_meta_by_ids (consolidator 裸 SQL 替代) 经租户作用域。"""
    store_a = _make_store(tmp_path, "acme", "t1")
    store_b = _make_store(tmp_path, "globex", "t2")
    await store_a.init_schema()

    ep_id = await store_a.store_episode("agent_x", {"session_id": "s1", "user_id": "u1", "content": "A 的记忆"})
    # 租户 B 拿 A 的 id 读元数据 → 空 (租户谓词拦截)
    assert await store_b.get_episode_meta_by_ids([ep_id]) == []
    meta = await store_a.get_episode_meta_by_ids([ep_id])
    assert len(meta) == 1 and meta[0]["id"] == ep_id and meta[0]["user_id"] == "u1"


@pytest.mark.asyncio
async def test_governance_audit_revision_tenant_tagged(tmp_path: Path) -> None:
    """治理审计/纠正历史行打租户标; 跨租户 list_audit 不可见。"""
    import aiosqlite

    from isac.memory.model.governance import MemoryGovernor

    store_a = _make_store(tmp_path, "acme", "t1")
    store_b = _make_store(tmp_path, "globex", "t2")
    await store_a.init_schema()

    ep_id = await store_a.store_episode("agent_x", {"session_id": "s1", "user_id": "u1", "content": "原始内容"})
    governor_a = MemoryGovernor(store_a)
    governor_b = MemoryGovernor(store_b)

    assert await governor_a.correct(ep_id, "纠正后的内容", "agent_x", operator="op_a") is True
    # B 对 A 的条目治理一律拒绝 (U0 Fix-85 回归)
    assert await governor_b.freeze(ep_id, "agent_x") is False
    assert await governor_b.delete(ep_id, "agent_x") is False
    # 审计可见性: A 有记录, B 看不到 (list_audit 经租户作用域)
    audit_a = await governor_a.list_audit(ep_id)
    assert any(a["action"] == "correct" for a in audit_a)
    assert await governor_b.list_audit(ep_id) == []
    # revision/audit 行确实打了 A 的租户标
    async with aiosqlite.connect(store_a.db_path) as db:
        db.row_factory = aiosqlite.Row
        rev = (await (await db.execute("SELECT * FROM memory_revisions")).fetchall())[0]
        assert rev["organization_id"] == "acme" and rev["tenant_id"] == "t1"
        audit_row = (await (await db.execute("SELECT * FROM memory_audit")).fetchall())[0]
        assert audit_row["organization_id"] == "acme" and audit_row["tenant_id"] == "t1"


@pytest.mark.asyncio
async def test_default_tenant_zero_behavior(tmp_path: Path) -> None:
    """tenancy 未启用/默认租户: 四表读写零行为变化 (不打标不作用域)。"""
    store = MetadataStore(str(tmp_path / "memory.db"))  # 无 guard
    await store.init_schema()
    await store.upsert_person_profile("agent_x", {"person_id": "u1", "name": "张三"})
    await store.upsert_jargon("agent_x", "词", "义")
    assert (await store.get_person_profile("agent_x", "u1"))["name"] == "张三"
    assert [j["word"] for j in await store.list_jargon("agent_x")] == ["词"]
    # 行仍带 default 标 (升级多租户时存量不需回填)
    import aiosqlite

    async with aiosqlite.connect(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        row = (await (await db.execute("SELECT * FROM person_profiles")).fetchall())[0]
        assert row["organization_id"] == "default" and row["tenant_id"] == "default"


# ── 裸 SQL 绕过点审计 ────────────────────────────────────────


def test_no_raw_sql_bypass_in_memory_domain() -> None:
    """审计确认无裸 SQL 绕过点: 记忆域直连 metadata.db 仅限机制层允许清单。

    U4 前 consolidator._fetch_episode_meta / control routes_memory 直连 db_path
    裸 SQL 绕过租户机制; 修复后除机制层 (tenant_bound/metadata 本身) 与独立库
    (vector/graph, 非租户表) 外, isac/ 内不得再有 aiosqlite.connect 直连。
    """
    root = Path(__file__).resolve().parents[2] / "isac"
    allowed = {
        # 机制层本体 (租户原语唯一入口 + 其宿主)
        root / "memory" / "storage" / "tenant_bound.py",
        root / "memory" / "storage" / "metadata.py",
        # 独立库 (非租户表: 向量按 namespace 文件隔离, 图谱按 namespace 键隔离)
        root / "memory" / "storage" / "vector.py",
        root / "memory" / "storage" / "graph.py",
        # 非记忆域 (网关/控制面/会话事件等各自的库)
        root / "artifacts" / "store.py",
        root / "control" / "api" / "routes_providers.py",
        # Fix-94: routes_sessions.py 改经 store._tenant_db.scoped() 后不再裸连,
        # 从允许清单移除以收紧守卫 (再引入 aiosqlite.connect 会被本测试拦下)。
        root / "gateway" / "identity" / "resolver.py",
        root / "gateway" / "session.py",
        root / "gateway" / "user_mapper.py",
        root / "observability" / "usage" / "storage.py",
        root / "runtime" / "subagent" / "journal.py",
        root / "runtime" / "tenancy" / "manager.py",
        root / "session" / "event_store.py",
    }
    offenders = []
    for py_file in root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if "aiosqlite.connect" in text and py_file not in allowed:
            offenders.append(str(py_file.relative_to(root.parent)))
    assert offenders == [], f"发现裸 aiosqlite.connect 绕过点: {offenders}"


# ── 工具取键口径 (master_id + namespace) ─────────────────────


@pytest.mark.asyncio
async def test_query_memory_tool_uses_master_id() -> None:
    """U4: query_memory 工具 user_id 取 user_profile.user_id (master_id),
    无 user_profile 时回落平台 session.user_id (修私聊工具召回系统性漏)。"""
    from isac.agent.tools.base import ToolContext
    from isac.agent.tools.social.query_memory import QueryMemoryTool
    from isac.channel.model import ISACMessage
    from isac.core.types import AgentContext
    from isac.gateway.models import Session, UserProfile

    captured: dict = {}

    class _Mem:
        async def search(self, query, top_k=3, agent_id="", user_id="", group_id=""):
            captured["user_id"] = user_id
            return []

    def _ctx(user_profile) -> ToolContext:
        session = Session(session_id="s1", user_id="platform_u1", agent_id="agent1")
        msg = ISACMessage(
            msg_id="m1", platform="qq", timestamp=0, user_id="platform_u1",
            user_name="u", group_id=None, content="q",
        )
        return ToolContext(
            args={"query": "测试"},
            agent_context=AgentContext(session=session, user_profile=user_profile, current_message=msg),
            services={"memory": _Mem()},
        )

    # 有 user_profile → master_id
    await QueryMemoryTool().execute(_ctx(UserProfile(user_id="master_u1")))
    assert captured["user_id"] == "master_u1"
    # 无 user_profile → 回落平台 id (向后兼容)
    await QueryMemoryTool().execute(_ctx(None))
    assert captured["user_id"] == "platform_u1"


@pytest.mark.asyncio
async def test_query_person_profile_tool_key_unification() -> None:
    """U4: query_person_profile 工具 agent 键用 pipeline.namespace, person_id
    优先 master_id (与写侧口径一致)。"""
    from isac.agent.tools.base import ToolContext
    from isac.agent.tools.social.query_person_profile import QueryPersonProfileTool
    from isac.channel.model import ISACMessage
    from isac.core.types import AgentContext
    from isac.gateway.models import Session, UserProfile

    captured: dict = {}

    class _Meta:
        async def get_person_profile(self, agent_id, person_id):
            captured["agent_id"] = agent_id
            captured["person_id"] = person_id
            return None

    class _Mem:
        namespace = "acme:t1:agent1"
        metadata = _Meta()

    session = Session(session_id="s1", user_id="platform_u1", agent_id="agent1")
    msg = ISACMessage(
        msg_id="m1", platform="qq", timestamp=0, user_id="platform_u1",
        user_name="u", group_id=None, content="q",
    )
    ctx = ToolContext(
        args={"user_name": ""},  # 无显式参数 → 走 master_id 回落链
        agent_context=AgentContext(
            session=session, user_profile=UserProfile(user_id="master_u1"), current_message=msg
        ),
        services={"memory": _Mem()},
    )
    await QueryPersonProfileTool().execute(ctx)
    assert captured["agent_id"] == "acme:t1:agent1"  # namespace 键 (非裸 agent_id)
    assert captured["person_id"] == "master_u1"  # master_id (非平台 id)


@pytest.mark.asyncio
async def test_session_messages_endpoint_tenant_scoped(tmp_path: Path) -> None:
    """Fix-94: /sessions/{id}/messages 的底层查询必须走租户作用域 —— 此前裸 SQL
    直连 episodes, 多租户共库时任一租户可遍历 session_id 读到其他租户的会话原文。"""
    from isac.control.api.routes_sessions import _query_episodes_by_session

    store_a = _make_store(tmp_path, "acme", "t1")
    store_b = _make_store(tmp_path, "globex", "t2")
    await store_a.init_schema()

    # 租户 A 写入带 session_id 的 episode
    await store_a.store_episode(
        "agent_x",
        {"session_id": "sess-shared", "user_id": "u1", "content": "租户 A 的机密会话"},
    )

    # 租户 A 自己能读到
    rows_a = await _query_episodes_by_session(store_a, "sess-shared", 10)
    assert [r["content"] for r in rows_a] == ["租户 A 的机密会话"]
    # 租户 B 即使知道同一 session_id 也读不到 (租户谓词机制拦截)
    rows_b = await _query_episodes_by_session(store_b, "sess-shared", 10)
    assert rows_b == []
