"""N2 Memory 治理 Control API 路由 (MEMORY_DESIGN.md §7)。

N2 已落地: freeze/protect/correct/delete/restore/export 真实委托 MemoryGovernor
(操作 episodes 治理列 + memory_audit + memory_revisions 表)。Bearer Token 认证;
无 metadata_store 时整个路由不挂载 (404, 与 routes_memory 一致)。

CR2-Fix-10: 此前完全没有 scope 校验 (绕开 Fix-12 建立的 Token Scope 模型),
也没有接入项目统一审计日志 (只写内部 memory_audit 表, 查不到)。新增
memory:read (list_items) / memory:write (freeze/protect/correct/delete/restore)
scope, 并在每次写操作后追加调用项目统一的 _audit(), 落 data/audit.ndjson。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

# Request 必须在模块级导入: from __future__ import annotations 让注解变字符串,
# FastAPI 在路由注册时用模块命名空间解析 "Request", 函数内局部导入解析不到
# (与 routes_auth.py 的既有做法一致)。
from fastapi import Request

if TYPE_CHECKING:
    from isac.control.audit import AuditLog
    from isac.memory.storage.metadata import MetadataStore


def _resolve_operator(request: Any) -> str:
    """从请求解析操作者标识 (CR3-L5): Bearer Token 指纹 > WebUI 会话 > anonymous。

    落审计的是不可逆指纹 (token_fingerprint), 绝不落裸 Token。
    """
    from isac.control.auth import SESSION_COOKIE_NAME, extract_bearer, token_fingerprint

    bearer = extract_bearer(request.headers.get("authorization"))
    if bearer:
        return token_fingerprint(bearer)
    if request.cookies.get(SESSION_COOKIE_NAME):
        return "webui-session"
    return "anonymous"


def build_router(
    metadata_store: MetadataStore | None,
    auth_dependency: Any = None,
    scope_dependency: Any = None,
    audit_log: AuditLog | None = None,
    sparse_resolver: Callable[[str], Any] | None = None,
) -> Any:
    """构造 Memory 治理路由。无 metadata_store 时返回 None (不挂载)。

    sparse_resolver (CR3-L3): namespace → SparseBM25Index 的解析函数, 由 main.py
    注入 (build_services 的 sparse_indexes.get); 未注入时治理操作跳过 BM25 同步。
    """
    if metadata_store is None:
        return None
    from fastapi import APIRouter, Depends

    from isac.memory.model import MemoryGovernor

    governor = MemoryGovernor(metadata_store, sparse_resolver=sparse_resolver)
    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["memory-admin"], dependencies=deps)
    # CR2-Fix-10: scope_dependency 为 None (未配置 control.tokens[]) 时
    # read_deps/write_deps 都是空列表, 只受上面的 auth_dependency 约束, 行为不变。
    read_deps = [Depends(scope_dependency("memory:read"))] if scope_dependency else []
    write_deps = [Depends(scope_dependency("memory:write"))] if scope_dependency else []

    @router.post("/memory/{agent_id}/items/{item_id}/freeze", dependencies=write_deps)
    async def freeze(agent_id: str, item_id: str, request: Request) -> dict:
        ok = await governor.freeze(item_id, agent_id, operator=_resolve_operator(request))
        path = f"/api/v1/memory/{agent_id}/items/{item_id}/freeze"
        await _audit_if_ok(audit_log, ok, "POST", path, "freeze_memory_item", item_id)
        return {"ok": ok, "detail": "frozen" if ok else "item not found or already frozen"}

    @router.post("/memory/{agent_id}/items/{item_id}/protect", dependencies=write_deps)
    async def protect(agent_id: str, item_id: str, request: Request) -> dict:
        ok = await governor.protect(item_id, agent_id, operator=_resolve_operator(request))
        path = f"/api/v1/memory/{agent_id}/items/{item_id}/protect"
        await _audit_if_ok(audit_log, ok, "POST", path, "protect_memory_item", item_id)
        return {"ok": ok, "detail": "protected" if ok else "item not found or already protected"}

    @router.patch("/memory/{agent_id}/items/{item_id}", dependencies=write_deps)
    async def correct(agent_id: str, item_id: str, payload: dict, request: Request) -> dict:
        """CR2-Fix-14: new_content 通过 JSON body 传入 (裸 str 参数会被 FastAPI
        绑成 query 参数, 长文本进 URL 会污染访问日志/代理场景), 与
        routes_agents.py::patch_agent 的 payload: dict 惯例一致。
        """
        new_content = str(payload.get("new_content", ""))
        ok = await governor.correct(item_id, new_content, agent_id, operator=_resolve_operator(request))
        path = f"/api/v1/memory/{agent_id}/items/{item_id}"
        await _audit_if_ok(audit_log, ok, "PATCH", path, "correct_memory_item", item_id)
        return {"ok": ok, "detail": "corrected with revision history" if ok else "item not found"}

    @router.delete("/memory/{agent_id}/items/{item_id}", dependencies=write_deps)
    async def delete(agent_id: str, item_id: str, request: Request) -> dict:
        ok = await governor.delete(item_id, agent_id, operator=_resolve_operator(request))
        path = f"/api/v1/memory/{agent_id}/items/{item_id}"
        await _audit_if_ok(audit_log, ok, "DELETE", path, "delete_memory_item", item_id)
        return {
            "ok": ok,
            "detail": "soft deleted" if ok else "item not found or protected (refused)",
        }

    @router.post("/memory/{agent_id}/items/{item_id}/restore", dependencies=write_deps)
    async def restore(agent_id: str, item_id: str, request: Request) -> dict:
        ok = await governor.restore(item_id, agent_id, operator=_resolve_operator(request))
        path = f"/api/v1/memory/{agent_id}/items/{item_id}/restore"
        await _audit_if_ok(audit_log, ok, "POST", path, "restore_memory_item", item_id)
        return {"ok": ok, "detail": "restored" if ok else "item not found"}

    @router.get("/memory/{agent_id}/items", dependencies=read_deps)
    async def list_items(agent_id: str, limit: int = 500, offset: int = 0) -> dict:
        items = await governor.export(agent_id, limit=limit, offset=offset)
        return {
            "ok": True,
            "count": len(items),
            "items": [
                {
                    "id": it.id,
                    "content": it.content,
                    "type": it.memory_type.value,
                    "frozen": it.metadata.get("frozen", 0),
                    "protected": it.metadata.get("protected", 0),
                    "deleted": it.metadata.get("deleted", 0),
                }
                for it in items
            ],
        }

    return router


async def _audit(
    audit_log: AuditLog | None,
    method: str,
    path: str,
    action: str,
    target: str,
) -> None:
    """记录审计日志 (audit_log 为 None 时跳过, 与 routes_agents.py 的既有约定一致)。"""
    if audit_log is None:
        return
    await audit_log.record(
        actor="authenticated",
        method=method,
        path=path,
        action=action,
        target=target,
        status_code=200,
    )


async def _audit_if_ok(
    audit_log: AuditLog | None,
    ok: bool,
    method: str,
    path: str,
    action: str,
    target: str,
) -> None:
    """治理操作成功时才记录审计 (失败的操作不应留下"已执行"的审计痕迹)。

    独立于 build_router 之外, 避免 5 个写端点各自内联 if 分支把
    build_router 的 mccabe 复杂度推高 (C901)。
    """
    if not ok:
        return
    await _audit(audit_log, method, path, action, target)
