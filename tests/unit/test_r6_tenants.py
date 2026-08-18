"""R6 租户控制面测试: TenantManager 存储 + routes_tenants 端点 + scope/审计。"""

from __future__ import annotations

from typing import Any

import pytest

from isac.runtime.tenancy.manager import TenantManager

# ── TenantManager 存储 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_create_get_list(tmp_path: object) -> None:
    db = str(tmp_path) + "/tenants.db"  # type: ignore[operator]
    mgr = TenantManager(db_path=db)
    t = await mgr.create("org_a", organization_id="acme", display_name="ACME")
    assert t.tenant_id == "org_a"
    assert t.organization_id == "acme"
    fetched = await mgr.get("org_a")
    assert fetched is not None
    assert fetched.display_name == "ACME"
    listed = await mgr.list_tenants()
    assert len(listed) == 1


@pytest.mark.asyncio
async def test_tenant_create_duplicate_raises(tmp_path: object) -> None:
    mgr = TenantManager(db_path=str(tmp_path) + "/t.db")  # type: ignore[operator]
    await mgr.create("dup")
    with pytest.raises(ValueError, match="已存在"):
        await mgr.create("dup")


@pytest.mark.asyncio
async def test_tenant_persistence_restart(tmp_path: object) -> None:
    """R6: 重启后新实例同 db_path 恢复既有租户 (照 UserMapper/SessionManager 同构)。"""
    db = str(tmp_path) + "/tenants.db"  # type: ignore[operator]
    mgr1 = TenantManager(db_path=db)
    await mgr1.create("persist_t", display_name="Persist")
    # 重启: 新实例
    mgr2 = TenantManager(db_path=db)
    listed = await mgr2.list_tenants()
    assert len(listed) == 1
    assert listed[0].tenant_id == "persist_t"
    assert listed[0].display_name == "Persist"


@pytest.mark.asyncio
async def test_tenant_member_add_remove(tmp_path: object) -> None:
    mgr = TenantManager(db_path=str(tmp_path) + "/t.db")  # type: ignore[operator]
    await mgr.create("t1")
    await mgr.add_member("t1", "user_1", member_type="user")
    t = await mgr.get("t1")
    assert len(t.members) == 1  # type: ignore[union-attr]
    assert t.members[0]["member_id"] == "user_1"  # type: ignore[union-attr]
    removed = await mgr.remove_member("t1", "user_1", member_type="user")
    assert removed is True
    t = await mgr.get("t1")
    assert len(t.members) == 0  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_tenant_add_member_nonexistent_tenant(tmp_path: object) -> None:
    mgr = TenantManager(db_path=str(tmp_path) + "/t.db")  # type: ignore[operator]
    with pytest.raises(ValueError, match="租户不存在"):
        await mgr.add_member("nope", "u1")


@pytest.mark.asyncio
async def test_tenant_delete(tmp_path: object) -> None:
    mgr = TenantManager(db_path=str(tmp_path) + "/t.db")  # type: ignore[operator]
    await mgr.create("t1")
    assert await mgr.delete("t1") is True
    assert await mgr.get("t1") is None
    assert await mgr.delete("t1") is False


@pytest.mark.asyncio
async def test_tenant_no_db_path_in_memory() -> None:
    """R6: 不传 db_path 时纯内存 (向后兼容)。"""
    mgr = TenantManager()
    await mgr.create("mem_t")
    assert await mgr.get("mem_t") is not None


# ── routes_tenants 端点 ─────────────────────────────────────


def _make_tenants_app(tenant_manager: Any) -> Any:
    from isac.control.api.server import create_control_app
    from isac.observability import get_default_metrics

    return create_control_app(
        type("A", (), {"list": lambda self: [], "get": lambda self, x: None})(),
        type("R", (), {})(), type("B", (), {})(), type("P", (), {})(),
        {"api_token": "t"}, metrics=get_default_metrics(), tenant_manager=tenant_manager,
    )


def test_routes_tenants_no_manager_not_mounted() -> None:
    """R6: 无 tenant_manager 时路由不挂载 (404)。"""
    from isac.control.api.server import create_control_app
    from isac.observability import get_default_metrics

    app = create_control_app(
        type("A", (), {"list": lambda self: [], "get": lambda self, x: None})(),
        type("R", (), {})(), type("B", (), {})(), type("P", (), {})(),
        {"api_token": "t"}, metrics=get_default_metrics(), tenant_manager=None,
    )
    from fastapi.testclient import TestClient

    resp = TestClient(app).get("/api/v1/tenants", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 404


def test_routes_tenants_crud(tmp_path: object) -> None:
    """R6-①: 租户 CRUD 端点 (create → get → list → delete)。"""
    mgr = TenantManager(db_path=str(tmp_path) + "/t.db")  # type: ignore[operator]
    from fastapi.testclient import TestClient

    client = TestClient(_make_tenants_app(mgr))
    h = {"Authorization": "Bearer t", "Content-Type": "application/json"}
    # create
    resp = client.post("/api/v1/tenants", json={"tenant_id": "t1", "display_name": "T1"}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == "t1"
    # duplicate → 409
    resp = client.post("/api/v1/tenants", json={"tenant_id": "t1"}, headers=h)
    assert resp.status_code == 409
    # get
    resp = client.get("/api/v1/tenants/t1", headers=h)
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "T1"
    # list
    resp = client.get("/api/v1/tenants", headers=h)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    # delete
    resp = client.delete("/api/v1/tenants/t1", headers=h)
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    # get after delete → 404
    resp = client.get("/api/v1/tenants/t1", headers=h)
    assert resp.status_code == 404


def test_routes_tenants_members(tmp_path: object) -> None:
    """R6-①: 成员 add/remove 端点。"""
    mgr = TenantManager(db_path=str(tmp_path) + "/t.db")  # type: ignore[operator]
    from fastapi.testclient import TestClient

    client = TestClient(_make_tenants_app(mgr))
    h = {"Authorization": "Bearer t", "Content-Type": "application/json"}
    client.post("/api/v1/tenants", json={"tenant_id": "t1"}, headers=h)
    # add member
    resp = client.post("/api/v1/tenants/t1/members", json={"member_id": "u1", "member_type": "user"}, headers=h)
    assert resp.status_code == 200
    # verify in get
    resp = client.get("/api/v1/tenants/t1", headers=h)
    assert len(resp.json()["members"]) == 1
    # remove member
    resp = client.delete("/api/v1/tenants/t1/members/u1?member_type=user", headers=h)
    assert resp.status_code == 200
    resp = client.get("/api/v1/tenants/t1", headers=h)
    assert len(resp.json()["members"]) == 0
