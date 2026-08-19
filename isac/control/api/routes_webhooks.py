"""Webhook 订阅与触发端点 (R2-③, SPECIFICATION.md 4.6)。

复用已实现的 WebhookManager (subscribe/unsubscribe/dispatch/trigger + SSRF 校验)。
此前 WebhookManager 类已完整但 main 不构造 + server 不挂载 → 死代码。本轮接线:
main 构造 WebhookManager + EventBus on_async 订阅 + AlertManager 注入 + 本路由挂载。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from isac.utils.ssrf import redact_url as _redact_url

if TYPE_CHECKING:
    from isac.control.audit import AuditLog
    from isac.control.webhooks import WebhookManager


def build_router(
    webhook_manager: WebhookManager,
    *,
    auth_dependency: Any = None,
    scope_dependency: Any = None,
    audit_log: AuditLog | None = None,
) -> Any:
    """构造 /webhooks + /automation/trigger 路由。

    订阅 CRUD (subscribe/unsubscribe/list) + 手动触发 (trigger)。写操作需
    webhook:write scope + 审计; 读用 webhook:read。端点逻辑抽到模块级 helper 降复杂度。
    """
    from fastapi import APIRouter, Depends, HTTPException

    router = APIRouter(
        tags=["webhooks"],
        dependencies=[Depends(auth_dependency)] if auth_dependency else [],
    )
    read_deps = [Depends(scope_dependency("webhook:read"))] if scope_dependency else []
    write_deps = [Depends(scope_dependency("webhook:write"))] if scope_dependency else []
    _http_exc = HTTPException  # 闭包内引用 (helper 在模块级)
    # #29 审计 actor 归因: handler 经此依赖拿真实调用方身份写入审计。
    caller_dep = Depends(auth_dependency) if auth_dependency else Depends(lambda: "anonymous")

    @router.get("/webhooks", dependencies=read_deps)
    async def list_webhooks(event: str | None = None) -> dict:
        return webhook_manager.list_subscriptions(event)

    @router.post("/webhooks", dependencies=write_deps)
    async def subscribe_webhook(body: dict, caller: str = caller_dep) -> dict:
        return await _do_subscribe(webhook_manager, audit_log, body, _http_exc, actor=caller)

    @router.delete("/webhooks", dependencies=write_deps)
    async def unsubscribe_webhook(event: str, url: str, caller: str = caller_dep) -> dict:
        webhook_manager.unsubscribe(event, url)
        await _audit_webhook(
            audit_log, "DELETE", "unsubscribe_webhook", event, f"url={_redact_url(url)}",
            actor=caller,
        )
        return {"status": "unsubscribed", "event": event, "url": url}

    @router.post("/automation/trigger", dependencies=write_deps)
    async def trigger_webhook(body: dict, caller: str = caller_dep) -> dict:
        return await _do_trigger(webhook_manager, audit_log, body, _http_exc, actor=caller)

    return router


async def _audit_webhook(
    audit_log: AuditLog | None, method: str, action: str, target: str, detail: str,
    actor: str = "authenticated",
) -> None:
    if audit_log is not None:
        await audit_log.record(
            actor=actor, method=method, path="/api/v1/webhooks",
            action=action, target=target, detail=detail, status_code=200,
        )


async def _do_subscribe(
    webhook_manager: Any, audit_log: AuditLog | None, body: dict, _http_exc: Any,
    actor: str = "authenticated",
) -> dict:
    event = str(body.get("event", "") or "")
    url = str(body.get("url", "") or "")
    if not event or not url:
        raise _http_exc(status_code=400, detail={"code": "INVALID_INPUT", "message": "event and url required"})
    try:
        webhook_manager.subscribe(event, url)
    except Exception as exc:  # noqa: BLE001 SSRFBlockedError 等
        raise _http_exc(status_code=400, detail={"code": "WEBHOOK_REJECTED", "message": str(exc)}) from exc
    await _audit_webhook(audit_log, "POST", "subscribe_webhook", event, f"url={_redact_url(url)}", actor=actor)
    return {"status": "subscribed", "event": event, "url": url}


async def _do_trigger(
    webhook_manager: Any, audit_log: AuditLog | None, body: dict, _http_exc: Any,
    actor: str = "authenticated",
) -> dict:
    event = str(body.get("event", "") or "")
    data = body.get("data", {}) or {}
    if not event:
        raise _http_exc(status_code=400, detail={"code": "INVALID_INPUT", "message": "event required"})
    result = await webhook_manager.trigger(event, data)
    if audit_log is not None:
        await audit_log.record(
            actor=actor, method="POST", path="/api/v1/automation/trigger",
            action="trigger_webhook", target=event, detail=f"targets={len(result)}", status_code=200,
        )
    return {"event": event, "delivered": result}
