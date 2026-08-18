"""R6-① 租户控制面路由 (DEVELOPMENT_PLAN.md §四 R6)。

暴露 TenantManager 为控制面 REST 入口: CRUD 租户 + 成员管理 + 按租户鉴权
(tenant:read/tenant:write scope)。无 tenant_manager 注入时整个路由不挂载 (404),
默认零行为变化。数据面隔离已在 MetadataStore 层由 TenantIsolationGuard 完成
(guard.enforce 跨租户互不可见), 本路由聚焦租户资源的控制面 CRUD。端点逻辑抽到
模块级 helper 降 build_router 复杂度 (仿 routes_webhooks 模式)。

Bearer Token 认证 + tenant:read / tenant:write scope; 写操作落项目统一审计。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.control.audit import AuditLog
    from isac.runtime.tenancy.manager import TenantManager


def _summarize(tenant: Any) -> dict:
    """租户摘要 (含成员)。"""
    return {
        "tenant_id": tenant.tenant_id,
        "organization_id": tenant.organization_id,
        "display_name": tenant.display_name,
        "state": tenant.state,
        "created_at": tenant.created_at,
        "members": list(getattr(tenant, "members", [])),
    }


async def _audit_tenant(audit_log: AuditLog | None, action: str, target: str, detail: str) -> None:
    if audit_log is not None:
        await audit_log.record(
            actor="authenticated", method="POST", path=f"/api/v1/tenants/{target}",
            action=action, target=target, detail=detail, status_code=200,
        )


async def _do_create(tenant_manager: Any, audit_log: AuditLog | None, body: dict, _http_exc: Any) -> dict:
    try:
        tenant = await tenant_manager.create(
            tenant_id=body.get("tenant_id") or None,
            organization_id=str(body.get("organization_id", "default")),
            display_name=str(body.get("display_name", "") or ""),
        )
    except ValueError as exc:
        raise _http_exc(status_code=409, detail={"code": "TENANT_EXISTS", "message": str(exc)}) from exc
    await _audit_tenant(audit_log, "create_tenant", tenant.tenant_id, f"org={tenant.organization_id}")
    return _summarize(tenant)


async def _do_add_member(
    tenant_manager: Any, audit_log: AuditLog | None, tenant_id: str, body: dict, _http_exc: Any,
) -> dict:
    member_id = str(body.get("member_id", "") or "")
    member_type = str(body.get("member_type", "user") or "user")
    if not member_id:
        raise _http_exc(status_code=400, detail={"code": "INVALID_INPUT", "message": "member_id required"})
    try:
        await tenant_manager.add_member(tenant_id, member_id, member_type=member_type)
    except ValueError as exc:
        raise _http_exc(status_code=404, detail={"code": "TENANT_NOT_FOUND", "message": str(exc)}) from exc
    await _audit_tenant(audit_log, "add_tenant_member", tenant_id, f"member={member_id}")
    return {"status": "added", "tenant_id": tenant_id, "member_id": member_id}


async def _do_remove_member(
    tenant_manager: Any, audit_log: AuditLog | None, tenant_id: str, member_id: str, member_type: str,
    _http_exc: Any,
) -> dict:
    removed = await tenant_manager.remove_member(tenant_id, member_id, member_type=member_type)
    if not removed:
        raise _http_exc(status_code=404, detail={"code": "MEMBER_NOT_FOUND", "message": member_id})
    await _audit_tenant(audit_log, "remove_tenant_member", tenant_id, f"member={member_id}")
    return {"status": "removed", "tenant_id": tenant_id, "member_id": member_id}


def build_router(
    tenant_manager: TenantManager | None,
    *,
    auth_dependency: Any = None,
    scope_dependency: Any = None,
    audit_log: AuditLog | None = None,
) -> Any:
    """构造租户控制面路由。无 tenant_manager 时返回 None (不挂载)。"""
    if tenant_manager is None:
        return None
    from fastapi import APIRouter, Depends, HTTPException

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["tenants"], dependencies=deps)
    read_deps = [Depends(scope_dependency("tenant:read"))] if scope_dependency else []
    write_deps = [Depends(scope_dependency("tenant:write"))] if scope_dependency else []
    _http_exc = HTTPException

    @router.get("/tenants", dependencies=read_deps)
    async def list_tenants(organization: str | None = None) -> list[dict]:
        tenants = await tenant_manager.list_tenants(organization_id=organization)
        return [_summarize(t) for t in tenants]

    @router.post("/tenants", dependencies=write_deps)
    async def create_tenant(body: dict) -> dict:
        return await _do_create(tenant_manager, audit_log, body, _http_exc)

    @router.get("/tenants/{tenant_id}", dependencies=read_deps)
    async def get_tenant(tenant_id: str) -> dict:
        tenant = await tenant_manager.get(tenant_id)
        if tenant is None:
            raise _http_exc(status_code=404, detail={"code": "TENANT_NOT_FOUND", "message": tenant_id})
        return _summarize(tenant)

    @router.delete("/tenants/{tenant_id}", dependencies=write_deps)
    async def delete_tenant(tenant_id: str) -> dict:
        deleted = await tenant_manager.delete(tenant_id)
        if not deleted:
            raise _http_exc(status_code=404, detail={"code": "TENANT_NOT_FOUND", "message": tenant_id})
        await _audit_tenant(audit_log, "delete_tenant", tenant_id, "deleted")
        return {"status": "deleted", "tenant_id": tenant_id}

    @router.post("/tenants/{tenant_id}/members", dependencies=write_deps)
    async def add_member(tenant_id: str, body: dict) -> dict:
        return await _do_add_member(tenant_manager, audit_log, tenant_id, body, _http_exc)

    @router.delete("/tenants/{tenant_id}/members/{member_id}", dependencies=write_deps)
    async def remove_member(tenant_id: str, member_id: str, member_type: str = "user") -> dict:
        return await _do_remove_member(
            tenant_manager, audit_log, tenant_id, member_id, member_type, _http_exc,
        )

    return router
