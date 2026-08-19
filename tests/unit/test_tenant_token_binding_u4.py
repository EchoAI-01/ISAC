"""#25 (U4): 完整租户鉴权 —— token↔tenant 绑定强制 + 删除级联。

此前租户控制面只有 scope 门禁 (tenant:read/write), 任何持 scope 的 token 可操作
**任意**租户; 删除租户也只删 tenants/tenant_members 两张控制面表, 数据面打标行
(episodes/person_profiles/…) 永久残留。本批做实两环:

验收:
- resolve_caller_tenant: tokens[].tenant_id 绑定解析 (未绑定/未配置 = "" 不限);
- 路由强制: 绑定 token 只能操作自己的租户 (跨租户 403 TENANT_FORBIDDEN,
  create 恒 403, list 只可见自己), 未绑定 = 管理身份全量;
- TenantManager.delete 级联: on_delete 回调被调用; 回调失败不推翻删除结果;
- make_metadata_cascade: 只清目标 tenant_id 打标行 (自适应含 tenant_id 列的表),
  其他租户行不受影响; db 不存在 no-op;
- _build_tenant_manager: memory.enabled 门控注入级联。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from isac.control.auth import parse_token_scopes, resolve_caller_tenant
from isac.runtime.tenancy.manager import TenantManager, make_metadata_cascade

# ── resolve_caller_tenant 口径 ────────────────────────────────


def test_resolve_caller_tenant_binding() -> None:
    tokens = parse_token_scopes({"tokens": [
        {"token": "tok-t1", "name": "t1-bot", "tenant_id": "t1", "scopes": ["tenant:read"]},
        {"token": "admin-tok", "name": "admin", "scopes": ["*"]},
    ]})
    assert tokens is not None
    assert resolve_caller_tenant(tokens, "Bearer tok-t1") == "t1"
    assert resolve_caller_tenant(tokens, "Bearer admin-tok") == ""  # 未绑定 = 不限
    assert resolve_caller_tenant(tokens, "Bearer unknown") == ""  # 未匹配 = 不限
    assert resolve_caller_tenant(tokens, None) == ""
    assert resolve_caller_tenant(None, "Bearer tok-t1") == ""  # 未配置 tokens[] = 不限


def test_resolve_caller_tenant_session_cookie() -> None:
    """会话 Cookie 认证路径同口径解析绑定 (Fix-17 双轨)。"""
    from isac.control.auth import generate_session_secret, sign_session_cookie

    tokens = parse_token_scopes({"tokens": [{"token": "tok-t1", "tenant_id": "t1", "scopes": []}]})
    secret = generate_session_secret()
    cookie = sign_session_cookie("tok-t1", secret)
    assert resolve_caller_tenant(tokens, None, session_cookie=cookie, session_secret=secret) == "t1"
    # Cookie 无效 → 不限 (与认证侧拒绝解耦, 认证失败会在 auth_dependency 先 401)
    assert resolve_caller_tenant(tokens, None, session_cookie="garbage", session_secret=secret) == ""


def test_parse_token_scopes_tenant_id_default_empty() -> None:
    tokens = parse_token_scopes({"tokens": [{"token": "x", "scopes": []}]})
    assert tokens is not None
    assert tokens[0].tenant_id == ""  # 缺省未绑定


# ── 路由强制 (TestClient 端到端) ──────────────────────────────


def _make_bound_app(tenant_manager: Any) -> Any:
    """带 tokens[] 绑定的控制面 app: t1/t2 各一个绑定 token + 一个管理 token。"""
    from isac.control.api.server import create_control_app
    from isac.observability import get_default_metrics

    config = {
        "tokens": [
            {"token": "tok-t1", "name": "t1-bot", "tenant_id": "t1",
             "scopes": ["tenant:read", "tenant:write"]},
            {"token": "tok-t2", "name": "t2-bot", "tenant_id": "t2",
             "scopes": ["tenant:read", "tenant:write"]},
            {"token": "admin-tok", "name": "admin", "scopes": ["*"]},
        ],
    }
    return create_control_app(
        type("A", (), {"list": lambda self: [], "get": lambda self, x: None})(),
        type("R", (), {})(), type("B", (), {})(), type("P", (), {})(),
        config, metrics=get_default_metrics(), tenant_manager=tenant_manager,
    )


def test_bound_token_restricted_to_own_tenant(tmp_path: object) -> None:
    """绑定 t1 的 token: 只能操作 t1; 跨租户 get/delete/成员管理一律 403。"""
    from fastapi.testclient import TestClient

    mgr = TenantManager(db_path=str(tmp_path) + "/t.db")  # type: ignore[operator]
    client = TestClient(_make_bound_app(mgr))
    admin_h = {"Authorization": "Bearer admin-tok", "Content-Type": "application/json"}
    t1_h = {"Authorization": "Bearer tok-t1", "Content-Type": "application/json"}

    # 管理 token 先建两个租户
    assert client.post("/api/v1/tenants", json={"tenant_id": "t1"}, headers=admin_h).status_code == 200
    assert client.post("/api/v1/tenants", json={"tenant_id": "t2"}, headers=admin_h).status_code == 200

    # 绑定 token 操作自己的租户 → 200
    assert client.get("/api/v1/tenants/t1", headers=t1_h).status_code == 200
    resp = client.post("/api/v1/tenants/t1/members", json={"member_id": "u1"}, headers=t1_h)
    assert resp.status_code == 200
    assert client.delete("/api/v1/tenants/t1/members/u1?member_type=user", headers=t1_h).status_code == 200

    # 跨租户 → 403 TENANT_FORBIDDEN
    resp = client.get("/api/v1/tenants/t2", headers=t1_h)
    assert resp.status_code == 403 and resp.json()["detail"]["code"] == "TENANT_FORBIDDEN"
    assert client.delete("/api/v1/tenants/t2", headers=t1_h).status_code == 403
    assert client.post("/api/v1/tenants/t2/members", json={"member_id": "x"}, headers=t1_h).status_code == 403

    # list 只可见自己的租户
    listed = client.get("/api/v1/tenants", headers=t1_h).json()
    assert [t["tenant_id"] for t in listed] == ["t1"]
    # 管理 token 仍全量可见
    assert len(client.get("/api/v1/tenants", headers=admin_h).json()) == 2


def test_bound_token_cannot_create_tenant(tmp_path: object) -> None:
    """绑定 token 创建租户恒 403 (创建必然产生非自己的租户)。"""
    from fastapi.testclient import TestClient

    mgr = TenantManager(db_path=str(tmp_path) + "/t.db")  # type: ignore[operator]
    client = TestClient(_make_bound_app(mgr))
    resp = client.post(
        "/api/v1/tenants", json={"tenant_id": "t3"},
        headers={"Authorization": "Bearer tok-t1", "Content-Type": "application/json"},
    )
    assert resp.status_code == 403 and resp.json()["detail"]["code"] == "TENANT_FORBIDDEN"
    # 即使指定 tenant_id == 绑定值也不允许 (创建语义只属于管理身份)
    resp = client.post(
        "/api/v1/tenants", json={"tenant_id": "t1"},
        headers={"Authorization": "Bearer tok-t1", "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_unbound_tokens_keep_full_access(tmp_path: object) -> None:
    """未配置 tokens[] (扁平 api_token) 时行为与 #25 之前完全一致 (向后兼容)。"""
    from fastapi.testclient import TestClient

    from isac.control.api.server import create_control_app
    from isac.observability import get_default_metrics

    mgr = TenantManager(db_path=str(tmp_path) + "/t.db")  # type: ignore[operator]
    app = create_control_app(
        type("A", (), {"list": lambda self: [], "get": lambda self, x: None})(),
        type("R", (), {})(), type("B", (), {})(), type("P", (), {})(),
        {"api_token": "t"}, metrics=get_default_metrics(), tenant_manager=mgr,
    )
    client = TestClient(app)
    h = {"Authorization": "Bearer t", "Content-Type": "application/json"}
    assert client.post("/api/v1/tenants", json={"tenant_id": "any1"}, headers=h).status_code == 200
    assert client.post("/api/v1/tenants", json={"tenant_id": "any2"}, headers=h).status_code == 200
    assert len(client.get("/api/v1/tenants", headers=h).json()) == 2
    assert client.delete("/api/v1/tenants/any1", headers=h).status_code == 200


# ── 删除级联 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_invokes_on_delete_cascade() -> None:
    calls: list[str] = []

    async def _cascade(tenant_id: str) -> None:
        calls.append(tenant_id)

    mgr = TenantManager(on_delete=_cascade)
    await mgr.create("t1")
    assert await mgr.delete("t1") is True
    assert calls == ["t1"]
    # 租户不存在 → 删除失败, 不触发级联
    assert await mgr.delete("nope") is False
    assert calls == ["t1"]


@pytest.mark.asyncio
async def test_cascade_failure_does_not_flip_delete() -> None:
    """级联失败 best-effort: 租户资源已删, 删除结果不推翻, 异常不冒泡。"""

    async def _boom(tenant_id: str) -> None:
        raise RuntimeError("db locked")

    mgr = TenantManager(on_delete=_boom)
    await mgr.create("t1")
    assert await mgr.delete("t1") is True
    assert await mgr.get("t1") is None


@pytest.mark.asyncio
async def test_make_metadata_cascade_purges_only_target_tenant(tmp_path: Path) -> None:
    """级联只清目标租户打标行 (episodes/person_profiles), 其他租户不受影响。"""
    import aiosqlite

    from isac.memory.storage.metadata import MetadataStore
    from isac.runtime.tenancy.isolation import TenantIsolationGuard
    from isac.runtime.tenancy.models import TenantContext

    db_path = str(tmp_path / "metadata.db")

    def _store(tenant: str) -> MetadataStore:
        return MetadataStore(
            db_path,
            tenant_guard=TenantIsolationGuard(enabled=True),
            tenant_context=TenantContext(organization_id="acme", tenant_id=tenant),
        )

    store_t1, store_t2 = _store("t1"), _store("t2")
    await store_t1.init_schema()
    await store_t1.store_episode("agent_x", {"session_id": "s1", "user_id": "u1", "content": "t1 记忆"})
    await store_t1.upsert_person_profile("acme:t1:agent_x", {"person_id": "u1", "name": "张三"})
    await store_t2.store_episode("agent_x", {"session_id": "s2", "user_id": "u2", "content": "t2 记忆"})

    await make_metadata_cascade(db_path)("t1")

    async def _count(table: str, tenant: str) -> int:
        async with aiosqlite.connect(db_path) as db:
            cur = await db.execute(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = ?", (tenant,))
            return int((await cur.fetchone())[0])

    assert await _count("episodes", "t1") == 0
    assert await _count("person_profiles", "t1") == 0
    assert await _count("episodes", "t2") == 1  # 其他租户行不受影响


@pytest.mark.asyncio
async def test_make_metadata_cascade_missing_db_noop(tmp_path: Path) -> None:
    """metadata.db 不存在 (memory 从未启用) → no-op 不抛异常。"""
    await make_metadata_cascade(str(tmp_path / "nope.db"))("t1")


def test_build_tenant_manager_cascade_gating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_build_tenant_manager: memory.enabled 门控级联注入; tenancy 关闭 → None。"""
    from isac.runtime.tenancy import manager as mgr_mod

    monkeypatch.setattr(mgr_mod, "_DATA_DIR", tmp_path)
    assert mgr_mod._build_tenant_manager({"enabled": False}, {"enabled": True}) is None
    with_cascade = mgr_mod._build_tenant_manager({"enabled": True}, {"enabled": True})
    assert with_cascade is not None and with_cascade._on_delete is not None
    without = mgr_mod._build_tenant_manager({"enabled": True}, {"enabled": False})
    assert without._on_delete is None
    assert mgr_mod._build_tenant_manager({"enabled": True})._on_delete is None


@pytest.mark.asyncio
async def test_delete_with_db_persistence_cascades(tmp_path: Path) -> None:
    """持久化路径 (重启后仅库有) 删除同样触发级联。"""
    calls: list[str] = []

    async def _cascade(tenant_id: str) -> None:
        calls.append(tenant_id)

    db = str(tmp_path / "tenants.db")
    mgr1 = TenantManager(db_path=db)
    await mgr1.create("t1")
    # 重启: 新实例带级联 (内存为空, 仅库有)
    mgr2 = TenantManager(db_path=db, on_delete=_cascade)
    assert await mgr2.delete("t1") is True
    assert calls == ["t1"]
