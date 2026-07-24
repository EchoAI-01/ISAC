"""路由规则与互联 Link 端点 (SPECIFICATION.md 4.4)。

Bearer Token 认证 + 规则持久化 (router/rules.py save_rules) + Link 持久化 (data/links.jsonc) + 审计日志。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.control.audit import AuditLog
    from isac.router.router import MessageRouter
    from isac.runtime.bus import InterAgentBus


def build_router(
    router: MessageRouter,
    bus: InterAgentBus,
    auth_dependency: Any = None,
    audit_log: AuditLog | None = None,
    routing_rules_path: str = "data/routing.jsonc",
    links_path: str = "data/links.jsonc",
) -> Any:
    from fastapi import APIRouter, Depends

    from isac.router.rules import save_rules
    from isac.router.types import ChannelBinding, RoutingRules
    from isac.runtime.bus import InterAgentLink

    api = APIRouter(
        tags=["routing"],
        dependencies=[Depends(auth_dependency)] if auth_dependency else [],
    )

    @api.get("/routing/rules")
    async def get_rules() -> dict:
        rules = router.get_rules()
        return {
            "bindings": [vars(b) for b in rules.bindings],
            "default_agents": rules.default_agents,
        }

    @api.put("/routing/rules")
    async def put_rules(body: dict) -> dict:
        rules = RoutingRules(
            bindings=[ChannelBinding(**b) for b in body.get("bindings", [])],
            default_agents=dict(body.get("default_agents", {})),
        )
        router.set_rules(rules)
        save_rules(Path(routing_rules_path), rules)
        if audit_log is not None:
            await audit_log.record(
                actor="authenticated",
                method="PUT",
                path="/api/v1/routing/rules",
                action="update_routing_rules",
                detail=f"{len(rules.bindings)} bindings",
                status_code=200,
            )
        return {"status": "updated"}

    @api.get("/links")
    async def list_links() -> list[dict]:
        return [vars(link) for link in bus.list_links()]

    @api.post("/links")
    async def add_link(body: dict) -> dict:
        link = InterAgentLink(**body)
        # add_link 内部已触发 _trigger_persist; 但 routes_routing 持有独立的
        # _persist_links 路径, 用它把磁盘写入错误回传 500 (in-memory 状态已变更,
        # 调用方需要知道不一致) (CODE_REVIEW_REPORT.md #20)。
        bus.add_link(link)
        _persist_links_or_raise(bus, Path(links_path))
        await _audit_link_change(
            audit_log, method="POST", path="/api/v1/links", action="add_link",
            target=f"{link.from_agent}->{link.to_agent}",
        )
        return {"status": "added"}

    @api.delete("/links")
    async def remove_link(from_agent: str, to_agent: str) -> dict:
        bus.remove_link(from_agent, to_agent)
        _persist_links_or_raise(bus, Path(links_path))
        await _audit_link_change(
            audit_log, method="DELETE", path="/api/v1/links", action="remove_link",
            target=f"{from_agent}->{to_agent}",
        )
        return {"status": "removed"}

    return api


def _persist_links_or_raise(bus: InterAgentBus, path: Path) -> None:
    """持久化失败抛 HTTPException(500), 让 API 层把磁盘/内存不一致暴露给调用方
    (CODE_REVIEW_REPORT.md #20)。"""
    from fastapi import HTTPException

    try:
        _persist_links(bus, path)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "LINK_PERSIST_FAILED", "message": str(exc)},
        ) from exc


async def _audit_link_change(
    audit_log: AuditLog | None,
    *,
    method: str,
    path: str,
    action: str,
    target: str,
) -> None:
    """Link 变更的统一审计记录 (audit_log 为 None 时跳过)。"""
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


def _persist_links(bus: InterAgentBus, path: Path) -> None:
    """把所有 Link 持久化到 data/links.jsonc。

    失败时抛异常给调用方, 由 API 层返回 500 (CODE_REVIEW_REPORT.md #20)。
    """
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    links = [vars(link) for link in bus.list_links()]
    path.write_text(json.dumps({"links": links}, ensure_ascii=False, indent=2), encoding="utf-8")
