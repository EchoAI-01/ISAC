"""身份归一控制面路由 (S4, DEVELOPMENT_PLAN.md §四 P4)。

把已实现的 IdentityResolver 暴露为控制面 REST 入口:
- POST /identity/bind: 把一个平台账号绑定到已知 person (verified=1)
- GET  /identity/conflicts: 读取未裁决的低置信度冲突记录
- POST /identity/conflicts/{conflict_id}/resolve: 人工裁决 (标记 resolved + 更新 person_id)

无 identity_resolver 注入时整个路由不挂载 (返回 None, 与 routes_workflows 一致);
main.py 仅在 identity.enabled=true 时构造并注入 resolver, 默认零行为变化。
Bearer Token 认证 + identity:read / identity:write scope; 写操作落项目统一审计。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import Request
from pydantic import BaseModel

if TYPE_CHECKING:
    from isac.control.audit import AuditLog
    from isac.gateway.identity.resolver import IdentityResolver


class BindIdentityRequest(BaseModel):
    """bind 请求体 (模块顶层定义, 让 FastAPI 在路由注册时能从模块命名空间解析类型)。"""

    person_id: str
    platform: str
    platform_user_id: str
    display_name: str = ""
    connection_id: str = ""


class ResolveConflictRequest(BaseModel):
    """人工裁决请求体 (同上)。"""

    person_id: str


def _resolve_operator(request: Any) -> str:
    """解析操作者标识: Bearer Token 指纹 > WebUI 会话 > anonymous (落不可逆指纹)。"""
    from isac.control.auth import SESSION_COOKIE_NAME, extract_bearer, token_fingerprint

    bearer = extract_bearer(request.headers.get("authorization"))
    if bearer:
        return token_fingerprint(bearer)
    if request.cookies.get(SESSION_COOKIE_NAME):
        return "webui-session"
    return "anonymous"


def build_router(
    identity_resolver: IdentityResolver | None,
    auth_dependency: Any = None,
    scope_dependency: Any = None,
    audit_log: AuditLog | None = None,
) -> Any:
    """构造身份归一控制面路由。无 identity_resolver 时返回 None (不挂载)。"""
    if identity_resolver is None:
        return None
    from fastapi import APIRouter, Depends, HTTPException

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["identity"], dependencies=deps)
    read_deps = [Depends(scope_dependency("identity:read"))] if scope_dependency else []
    write_deps = [Depends(scope_dependency("identity:write"))] if scope_dependency else []

    @router.post("/identity/bind", dependencies=write_deps)
    async def bind_identity(body: BindIdentityRequest, request: Request) -> dict:
        from isac.gateway.identity.models import PlatformIdentity

        identity = PlatformIdentity(
            platform=body.platform,
            connection_id=body.connection_id,
            platform_user_id=body.platform_user_id,
            display_name=body.display_name,
        )
        ok = await identity_resolver.bind(body.person_id, identity)
        operator = _resolve_operator(request)
        status_code = 200 if ok else 400
        await _audit(
            audit_log,
            "POST",
            "/api/v1/identity/bind",
            "bind_identity",
            body.person_id,
            actor=operator,
            status_code=status_code,
        )
        if not ok:
            raise HTTPException(status_code=status_code, detail="identity bind failed")
        return {"person_id": body.person_id, "platform": body.platform, "bound": True}

    @router.get("/identity/conflicts", dependencies=read_deps)
    async def list_conflicts() -> list[dict]:
        return identity_resolver.list_conflicts()

    @router.post(
        "/identity/conflicts/{conflict_id}/resolve", dependencies=write_deps
    )
    async def resolve_conflict(
        conflict_id: str, body: ResolveConflictRequest, request: Request
    ) -> dict:
        ok = await identity_resolver.resolve_conflict(conflict_id, body.person_id)
        operator = _resolve_operator(request)
        status_code = 200 if ok else 404
        await _audit(
            audit_log,
            "POST",
            f"/api/v1/identity/conflicts/{conflict_id}/resolve",
            "resolve_identity_conflict",
            conflict_id,
            actor=operator,
            status_code=status_code,
        )
        if not ok:
            raise HTTPException(status_code=status_code, detail="conflict not found")
        return {"conflict_id": conflict_id, "resolved": True, "person_id": body.person_id}

    return router


async def _audit(
    audit_log: AuditLog | None,
    method: str,
    path: str,
    action: str,
    target: str,
    *,
    actor: str = "authenticated",
    status_code: int = 200,
) -> None:
    """记录审计 (audit_log 为 None 时跳过, 与其他控制面路由一致)。"""
    if audit_log is None:
        return
    await audit_log.record(
        actor=actor,
        method=method,
        path=path,
        action=action,
        target=target,
        status_code=status_code,
    )
