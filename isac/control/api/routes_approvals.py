"""U5 审批控制面路由 (HITL 第二回流路径: 运维侧审批)。

端点:
- GET  /approvals                列出 pending 审批
- POST /approvals/{id}/decide    对 pending 审批做出决定 {"decision": "approved"|"rejected"}
- GET  /approvals/history        决策留痕查询 (U1 事件表 tool.outcome 的决策记录)

IM 回复是另一条回流路径 (process_message 入口拦截 "同意/拒绝 <审批码>")。
Bearer Token 认证; approval_gate 未注入时整个路由不挂载 (404)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.agent.tools.approval import ApprovalGate


async def _collect_decision_records(session_event_store: Any, limit: int) -> list[dict]:
    """U5: 从 U1 事件表聚合全部 tool.* 决策记录 (按时间倒序, 截断到 limit)。"""
    records: list[dict] = []
    for key in await session_event_store.list_session_keys():
        events = await session_event_store.fetch_recent(key, limit=limit)
        for event in events:
            if event.event_type not in ("tool.called", "tool.outcome"):
                continue
            records.append(
                {
                    "session_key": event.session_key,
                    "seq": event.seq,
                    "event_type": event.event_type,
                    "timestamp": event.timestamp,
                    "payload": event.payload,
                }
            )
    records.sort(key=lambda r: r["timestamp"], reverse=True)
    return records[: max(1, int(limit))]


def _normalize_decision(payload: dict | None) -> str | None:
    """decision 字段规范化 (approved/rejected); 非法值返回 None。"""
    decision = str((payload or {}).get("decision", "") or "").strip().lower()
    return decision if decision in ("approved", "rejected") else None


async def _do_decide(
    approval_gate: Any, audit_log: Any, approval_id: str, decision: str, _http_exc: Any
) -> dict:
    """decide 端点主体 (抽自 build_router 降 C901)。"""
    ok = approval_gate.decide(approval_id, decision, decider="human:control_plane")
    if not ok:
        raise _http_exc(status_code=404, detail="审批不存在或已过期")
    if audit_log is not None:
        try:
            # Fix-92: 此前误把 AuditLog 实例当可调用对象 `audit_log(...)` —— AuditLog
            # 无 __call__, 每次 decide 都抛 TypeError 又被静默吞掉, 导致 HITL 最关键
            # 写操作零审计。改为与其他路由一致的 record() 调用。
            await audit_log.record(
                actor="authenticated",
                method="POST",
                path=f"/api/v1/approvals/{approval_id}/decide",
                action="approval_decide",
                target=approval_id,
                detail=f"decision={decision}",
                status_code=200,
            )
        except Exception:  # noqa: BLE001 审计失败不阻塞审批 (但记日志不再静默)
            from isac.utils.logger import get_logger

            get_logger(__name__).warning(
                "审批决策审计写入失败", approval_id=approval_id, decision=decision, exc_info=True
            )
    return {"approval_id": approval_id, "decision": decision}


async def _do_history(session_event_store: Any, limit: int, _http_exc: Any) -> dict:
    """history 端点主体 (抽自 build_router 降 C901)。"""
    if session_event_store is None:
        return {"events": []}
    try:
        records = await _collect_decision_records(session_event_store, limit)
    except Exception as exc:  # noqa: BLE001
        raise _http_exc(status_code=500, detail=f"决策留痕查询失败: {exc}") from exc
    return {"events": records}


def build_router(
    approval_gate: ApprovalGate | None,
    auth_dependency: Any = None,
    scope_dependency: Any = None,
    audit_log: Any = None,
    session_event_store: Any = None,
) -> Any:
    """构造审批路由。approval_gate 为 None 时返回 None (不挂载)。"""
    if approval_gate is None:
        return None
    from fastapi import APIRouter, Depends, HTTPException, Query

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["approvals"], dependencies=deps)
    # 审批是写操作面 (能放行高危工具), scope 按 tools:write 收窄; 未配 tokens[]
    # 时 scope_dependency 为 None, 只受 auth_dependency 约束 (向后兼容)。
    write_deps = [Depends(scope_dependency("tools:write"))] if scope_dependency else []

    @router.get("/approvals")
    async def list_approvals() -> dict:
        return {"approvals": approval_gate.pending_requests()}

    @router.get("/approvals/history")
    async def approval_history(limit: int = Query(default=100, ge=1, le=500)) -> dict:
        """U5 决策留痕查询: 事件表全部 tool.* 决策记录 (decision/decider/reason)。"""
        return await _do_history(session_event_store, limit, HTTPException)

    @router.post("/approvals/{approval_id}/decide", dependencies=write_deps)
    async def decide_approval(approval_id: str, payload: dict) -> dict:
        decision = _normalize_decision(payload)
        if decision is None:
            raise HTTPException(status_code=400, detail="decision 必须是 approved 或 rejected")
        return await _do_decide(approval_gate, audit_log, approval_id, decision, HTTPException)

    return router

