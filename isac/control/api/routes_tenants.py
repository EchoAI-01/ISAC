"""R6-① 租户控制面路由 (DEVELOPMENT_PLAN.md §四 R6)。

暴露 TenantManager 为控制面 REST 入口: CRUD 租户 + 成员管理 + 按租户鉴权
(tenant:read/tenant:write scope)。无 tenant_manager 注入时整个路由不挂载 (404),
默认零行为变化。数据面隔离已在 MetadataStore 层由 TenantIsolationGuard 完成
(guard.enforce 跨租户互不可见), 本路由聚焦租户资源的控制面 CRUD。端点逻辑抽到
模块级 helper 降 build_router 复杂度 (仿 routes_webhooks 模式)。

Bearer Token 认证 + tenant:read / tenant:write scope; 写操作落项目统一审计。
#25 (U4): tokens[] 条目带 tenant_id 绑定时, 路由层强制调用方只能操作自己的
租户 (跨租户 403 TENANT_FORBIDDEN); 未绑定 = 管理身份不限租户。
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


async def _audit_tenant(
    audit_log: AuditLog | None, action: str, target: str, detail: str,
    actor: str = "authenticated",
) -> None:
    if audit_log is not None:
        await audit_log.record(
            actor=actor, method="POST", path=f"/api/v1/tenants/{target}",
            action=action, target=target, detail=detail, status_code=200,
        )


async def _do_create(
    tenant_manager: Any, audit_log: AuditLog | None, body: dict, _http_exc: Any,
    actor: str = "authenticated",
) -> dict:
    try:
        tenant = await tenant_manager.create(
            tenant_id=body.get("tenant_id") or None,
            organization_id=str(body.get("organization_id", "default")),
            display_name=str(body.get("display_name", "") or ""),
        )
    except ValueError as exc:
        raise _http_exc(status_code=409, detail={"code": "TENANT_EXISTS", "message": str(exc)}) from exc
    await _audit_tenant(audit_log, "create_tenant", tenant.tenant_id, f"org={tenant.organization_id}", actor=actor)
    return _summarize(tenant)


async def _do_add_member(
    tenant_manager: Any, audit_log: AuditLog | None, tenant_id: str, body: dict, _http_exc: Any,
    actor: str = "authenticated",
) -> dict:
    member_id = str(body.get("member_id", "") or "")
    member_type = str(body.get("member_type", "user") or "user")
    if not member_id:
        raise _http_exc(status_code=400, detail={"code": "INVALID_INPUT", "message": "member_id required"})
    try:
        await tenant_manager.add_member(tenant_id, member_id, member_type=member_type)
    except ValueError as exc:
        raise _http_exc(status_code=404, detail={"code": "TENANT_NOT_FOUND", "message": str(exc)}) from exc
    await _audit_tenant(audit_log, "add_tenant_member", tenant_id, f"member={member_id}", actor=actor)
    return {"status": "added", "tenant_id": tenant_id, "member_id": member_id}


async def _do_remove_member(
    tenant_manager: Any, audit_log: AuditLog | None, tenant_id: str, member_id: str, member_type: str,
    _http_exc: Any,
    actor: str = "authenticated",
) -> dict:
    removed = await tenant_manager.remove_member(tenant_id, member_id, member_type=member_type)
    if not removed:
        raise _http_exc(status_code=404, detail={"code": "MEMBER_NOT_FOUND", "message": member_id})
    await _audit_tenant(audit_log, "remove_tenant_member", tenant_id, f"member={member_id}", actor=actor)
    return {"status": "removed", "tenant_id": tenant_id, "member_id": member_id}


# ── #25 (U4) 租户绑定强制 helper (模块级, 降 build_router 复杂度) ──


def _forbid_cross_tenant(_http_exc: Any, bound: str, tenant_id: str) -> None:
    """#25: 绑定租户的 token 操作其他租户 → 403 (未绑定 = 管理身份放行)。"""
    if bound and bound != tenant_id:
        raise _http_exc(
            status_code=403,
            detail={
                "code": "TENANT_FORBIDDEN",
                "message": f"token 已绑定租户 {bound}, 无权操作租户 {tenant_id}",
            },
        )


def _forbid_bound_create(_http_exc: Any, bound: str) -> None:
    """#25: 创建必然产生新租户, 绑定租户的 token 无权创建 (只能操作自己的)。"""
    if bound:
        raise _http_exc(
            status_code=403,
            detail={
                "code": "TENANT_FORBIDDEN",
                "message": f"token 已绑定租户 {bound}, 无权创建新租户",
            },
        )


async def _list_visible_tenants(
    tenant_manager: Any, organization: str | None, bound: str,
) -> list[dict]:
    """#25: 绑定租户的 token 只可见自己的租户; 未绑定 = 管理身份全量可见。"""
    tenants = await tenant_manager.list_tenants(organization_id=organization)
    if bound:
        tenants = [t for t in tenants if t.tenant_id == bound]
    return [_summarize(t) for t in tenants]


async def _do_get_tenant(tenant_manager: Any, tenant_id: str, _http_exc: Any) -> dict:
    tenant = await tenant_manager.get(tenant_id)
    if tenant is None:
        raise _http_exc(status_code=404, detail={"code": "TENANT_NOT_FOUND", "message": tenant_id})
    return _summarize(tenant)


async def _do_delete_tenant(
    tenant_manager: Any, audit_log: AuditLog | None, tenant_id: str, _http_exc: Any, actor: str,
) -> dict:
    deleted = await tenant_manager.delete(tenant_id)
    if not deleted:
        raise _http_exc(status_code=404, detail={"code": "TENANT_NOT_FOUND", "message": tenant_id})
    await _audit_tenant(audit_log, "delete_tenant", tenant_id, "deleted", actor=actor)
    return {"status": "deleted", "tenant_id": tenant_id}


def build_router(
    tenant_manager: TenantManager | None,
    *,
    auth_dependency: Any = None,
    scope_dependency: Any = None,
    audit_log: AuditLog | None = None,
    tokens: Any = None,
    session_secret: bytes | None = None,
) -> Any:
    """构造租户控制面路由。无 tenant_manager 时返回 None (不挂载)。

    #25 (U4): tokens/session_secret 注入后启用租户绑定强制 —— tokens[] 条目可
    带 tenant_id 绑定, 绑定非空的 token 只能操作自己的租户 (跨租户 403
    TENANT_FORBIDDEN); 未绑定/未配置 tokens[] = 管理身份不限租户 (向后兼容)。
    """
    if tenant_manager is None:
        return None
    from fastapi import APIRouter, Cookie, Depends, Header, HTTPException

    from isac.control.auth import SESSION_COOKIE_NAME, resolve_caller_tenant

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["tenants"], dependencies=deps)
    read_deps = [Depends(scope_dependency("tenant:read"))] if scope_dependency else []
    write_deps = [Depends(scope_dependency("tenant:write"))] if scope_dependency else []
    _http_exc = HTTPException
    # #29 审计 actor 归因: handler 经此依赖拿真实调用方身份写入审计。
    caller_dep = Depends(auth_dependency) if auth_dependency else Depends(lambda: "anonymous")

    def _bound_tenant(
        authorization: str | None = Header(default=None),
        session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ) -> str:
        """#25: 解析调用方 token 绑定的租户 ("" = 管理身份不限)。"""
        return resolve_caller_tenant(tokens, authorization, session_cookie, session_secret)

    bound_dep = Depends(_bound_tenant)

    @router.get("/tenants", dependencies=read_deps)
    async def list_tenants(organization: str | None = None, bound: str = bound_dep) -> list[dict]:
        return await _list_visible_tenants(tenant_manager, organization, bound)

    @router.post("/tenants", dependencies=write_deps)
    async def create_tenant(body: dict, caller: str = caller_dep, bound: str = bound_dep) -> dict:
        _forbid_bound_create(_http_exc, bound)
        return await _do_create(tenant_manager, audit_log, body, _http_exc, actor=caller)

    @router.get("/tenants/{tenant_id}", dependencies=read_deps)
    async def get_tenant(tenant_id: str, bound: str = bound_dep) -> dict:
        _forbid_cross_tenant(_http_exc, bound, tenant_id)
        return await _do_get_tenant(tenant_manager, tenant_id, _http_exc)

    @router.delete("/tenants/{tenant_id}", dependencies=write_deps)
    async def delete_tenant(tenant_id: str, caller: str = caller_dep, bound: str = bound_dep) -> dict:
        _forbid_cross_tenant(_http_exc, bound, tenant_id)
        return await _do_delete_tenant(tenant_manager, audit_log, tenant_id, _http_exc, actor=caller)

    @router.post("/tenants/{tenant_id}/members", dependencies=write_deps)
    async def add_member(tenant_id: str, body: dict, caller: str = caller_dep, bound: str = bound_dep) -> dict:
        _forbid_cross_tenant(_http_exc, bound, tenant_id)
        return await _do_add_member(tenant_manager, audit_log, tenant_id, body, _http_exc, actor=caller)

    @router.delete("/tenants/{tenant_id}/members/{member_id}", dependencies=write_deps)
    async def remove_member(
        tenant_id: str, member_id: str, member_type: str = "user",
        caller: str = caller_dep, bound: str = bound_dep,
    ) -> dict:
        _forbid_cross_tenant(_http_exc, bound, tenant_id)
        return await _do_remove_member(
            tenant_manager, audit_log, tenant_id, member_id, member_type, _http_exc, actor=caller,
        )

    return router
