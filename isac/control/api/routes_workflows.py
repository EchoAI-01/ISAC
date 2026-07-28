"""O3 Workflow 控制面路由 (骨架接线, DEVELOPMENT_PLAN.md §四 O3 / P5)。

把已实现的 WorkflowEngine 暴露为控制面 REST 入口: 列出 / 查看已登记工作流、启动一个
工作流。无 workflow_engine 注入时整个路由不挂载 (404, 与 routes_memory_admin 一致);
main.py 仅在 control.workflow.enabled=true 时构造并注入 engine, 默认零行为变化。

Bearer Token 认证 + workflow:read / workflow:write scope; 写操作 (start) 落项目
统一审计。Agent 侧「工具入口」(让 Agent 主动触发工作流) 留 P5 决策, 见 §四 O3。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# Request 必须模块级导入: from __future__ import annotations 让注解变字符串,
# FastAPI 在路由注册时用模块命名空间解析 "Request" (与 routes_memory_admin 一致)。
from fastapi import Request

if TYPE_CHECKING:
    from isac.control.audit import AuditLog
    from isac.runtime.workflow.engine import WorkflowEngine


def _resolve_operator(request: Any) -> str:
    """解析操作者标识: Bearer Token 指纹 > WebUI 会话 > anonymous (落不可逆指纹)。"""
    from isac.control.auth import SESSION_COOKIE_NAME, extract_bearer, token_fingerprint

    bearer = extract_bearer(request.headers.get("authorization"))
    if bearer:
        return token_fingerprint(bearer)
    if request.cookies.get(SESSION_COOKIE_NAME):
        return "webui-session"
    return "anonymous"


def _summarize(wf: Any) -> dict:
    """工作流摘要 (不外泄 stage 内部 params)。"""
    return {
        "workflow_id": wf.workflow_id,
        "name": wf.name,
        "status": str(wf.status),
        "stages": len(wf.stages),
    }


def build_router(
    workflow_engine: WorkflowEngine | None,
    auth_dependency: Any = None,
    scope_dependency: Any = None,
    audit_log: AuditLog | None = None,
) -> Any:
    """构造 Workflow 控制面路由。无 workflow_engine 时返回 None (不挂载)。"""
    if workflow_engine is None:
        return None
    from fastapi import APIRouter, Depends, HTTPException

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["workflows"], dependencies=deps)
    read_deps = [Depends(scope_dependency("workflow:read"))] if scope_dependency else []
    write_deps = [Depends(scope_dependency("workflow:write"))] if scope_dependency else []

    @router.get("/workflows", dependencies=read_deps)
    async def list_workflows() -> list[dict]:
        return [_summarize(wf) for wf in workflow_engine.list_workflows()]

    @router.get("/workflows/{workflow_id}", dependencies=read_deps)
    async def get_workflow(workflow_id: str) -> dict:
        wf = workflow_engine.get(workflow_id)
        if wf is None:
            raise HTTPException(status_code=404, detail="workflow not found")
        return _summarize(wf)

    @router.post("/workflows/{workflow_id}/start", dependencies=write_deps)
    async def start_workflow(workflow_id: str, request: Request) -> dict:
        if workflow_engine.get(workflow_id) is None:
            raise HTTPException(status_code=404, detail="workflow not found")
        status = await workflow_engine.start(workflow_id)
        operator = _resolve_operator(request)
        path = f"/api/v1/workflows/{workflow_id}/start"
        if str(status) == "failed":
            await _audit(
                audit_log,
                "POST",
                path,
                "start_workflow",
                workflow_id,
                actor=operator,
                status_code=500,
            )
            raise HTTPException(status_code=500, detail="workflow execution failed")
        await _audit(
            audit_log, "POST", path, "start_workflow", workflow_id, actor=operator,
        )
        return {"workflow_id": workflow_id, "status": str(status)}

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
