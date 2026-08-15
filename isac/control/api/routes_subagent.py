"""J4 SubAgent Control API 路由 (SPECIFICATION.md 4.4 / CONTROL_PLANE_SPEC.md)。

端点:
- POST   /agents/{agent_id}/subagent-runs        派生子任务
- GET    /agents/{agent_id}/subagent-runs        列出该 Agent 的子任务
- GET    /subagent-runs/{task_id}                查询单个子任务状态
- GET    /subagent-runs/{task_id}/events         分页读取事件
- POST   /subagent-runs/{task_id}/cancel         取消子任务 (幂等)

Bearer Token 认证 (依赖注入); 无 supervisor 时整个路由不挂载 (404)。
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.runtime.subagent.supervisor import SubAgentSupervisor


def build_router(
    supervisor: SubAgentSupervisor,
    auth_dependency: Any = None,
    scope_dependency: Any = None,
) -> Any:
    """构造 SubAgent Control API 路由。

    Args:
        supervisor: SubAgentSupervisor 实例 (必传; None 时不应调用本函数)
        auth_dependency: Bearer Token 认证依赖 (None 时跳过认证, 仅开发模式)
        scope_dependency: Fix-12, CONTROL_PLANE_SPEC.md §8.4 定义的
            subagent:run/read/cancel/log:read 四档 scope; None 时不做 scope 校验。
    """
    from fastapi import APIRouter, Depends, HTTPException, Query

    from isac.runtime.subagent.models import SubAgentPolicy, SubAgentTask

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["subagent"], dependencies=deps)
    run_deps = [Depends(scope_dependency("subagent:run"))] if scope_dependency else []
    read_deps = [Depends(scope_dependency("subagent:read"))] if scope_dependency else []
    cancel_deps = [Depends(scope_dependency("subagent:cancel"))] if scope_dependency else []
    log_read_deps = [Depends(scope_dependency("subagent:log:read"))] if scope_dependency else []

    @router.post("/agents/{agent_id}/subagent-runs", dependencies=run_deps)
    async def create_subagent_run(agent_id: str, payload: dict) -> dict:
        objective = str(payload.get("objective", "") or "").strip()
        if not objective:
            raise HTTPException(status_code=400, detail={"code": "INVALID_INPUT", "message": "objective required"})
        summary = str(payload.get("summary", "") or "")
        task_id = f"sub-{uuid.uuid4().hex[:12]}"
        task = SubAgentTask(
            task_id=task_id,
            parent_agent_id=agent_id,
            session_id=str(payload.get("session_id", "") or ""),
            trace_id=str(payload.get("trace_id", "") or task_id),
            objective=objective,
            context={"summary": summary},
            policy=SubAgentPolicy(),
            created_at=int(time.time()),
        )
        run = await supervisor.submit(task)
        return {"task_id": run.task_id, "status": run.status}

    @router.get("/agents/{agent_id}/subagent-runs", dependencies=read_deps)
    async def list_subagent_runs(agent_id: str) -> list[dict]:
        runs = await supervisor.list_runs(filters={"parent_agent_id": agent_id})
        return [_run_to_dict(run) for run in runs]

    @router.get("/subagent-runs", dependencies=read_deps)
    async def list_all_subagent_runs() -> list[dict]:
        """R2: 全局 SubAgent 任务列表 (无 parent_agent_id 过滤, 供 WebUI 系统扩展页)。"""
        runs = await supervisor.list_runs(filters={})
        return [_run_to_dict(run) for run in runs]

    @router.get("/subagent-runs/{task_id}", dependencies=read_deps)
    async def get_subagent_run(task_id: str) -> dict:
        run = await supervisor.get_status(task_id)
        if run is None:
            raise HTTPException(status_code=404, detail={"code": "SUBAGENT_NOT_FOUND", "message": task_id})
        return _run_to_dict(run)

    @router.get("/subagent-runs/{task_id}/events", dependencies=log_read_deps)
    async def get_subagent_events(
        task_id: str,
        after_seq: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
    ) -> dict:
        events = await supervisor.fetch_log(task_id, after_seq, limit)
        return {
            "task_id": task_id,
            "events": [
                {
                    "seq": e.seq,
                    "event_type": e.event_type,
                    "timestamp": e.timestamp,
                    "summary": e.summary,
                    "tool_name": e.tool_name,
                }
                for e in events
            ],
        }

    @router.post("/subagent-runs/{task_id}/cancel", dependencies=cancel_deps)
    async def cancel_subagent_run(task_id: str) -> dict:
        run = await supervisor.cancel(task_id)
        if run is None:
            raise HTTPException(status_code=404, detail={"code": "SUBAGENT_NOT_FOUND", "message": task_id})
        return _run_to_dict(run)

    return router


def _serialize_usage(usage: Any) -> dict | None:
    """Q5: TokenUsage → dict (None 时返回 None, 保持 JSON 兼容)。"""
    if usage is None:
        return None
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


def _run_to_dict(run: Any) -> dict:
    """SubAgentRun → dict (供 API 响应)。"""
    return {
        "task_id": run.task_id,
        "parent_agent_id": getattr(run, "parent_agent_id", ""),
        "status": run.status,
        "phase": run.phase,
        "started_at": run.started_at,
        "updated_at": run.updated_at,
        "finished_at": run.finished_at,
        "tokens_used": run.tokens_used,
        "tool_calls_used": run.tool_calls_used,
        "error_code": run.error_code,
        "error_summary": run.error_summary,
        "result_summary": getattr(run, "result_summary", ""),
        # Q5: usage (TokenUsage) + evidence_refs 此前在 _run_task 被丢弃, 现保留到
        # SubAgentRun 上, 控制面 list_subagent_runs / get_status 都能读到。
        "evidence_refs": getattr(run, "evidence_refs", []) or [],
        "usage": _serialize_usage(getattr(run, "usage", None)),
    }
