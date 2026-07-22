"""路由规则与互联 Link 端点 (SPECIFICATION.md 4.4)。

待落地: Token 认证 + 规则持久化 (router/rules.py save_rules) + 审计日志。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.router.router import MessageRouter
    from isac.runtime.bus import InterAgentBus


def build_router(router: MessageRouter, bus: InterAgentBus) -> Any:
    from fastapi import APIRouter

    from isac.router.types import ChannelBinding, RoutingRules
    from isac.runtime.bus import InterAgentLink

    api = APIRouter(tags=["routing"])

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
        return {"status": "updated"}

    @api.get("/links")
    async def list_links() -> list[dict]:
        return [vars(link) for link in bus.list_links()]

    @api.post("/links")
    async def add_link(body: dict) -> dict:
        bus.add_link(InterAgentLink(**body))
        return {"status": "added"}

    @api.delete("/links")
    async def remove_link(from_agent: str, to_agent: str) -> dict:
        bus.remove_link(from_agent, to_agent)
        return {"status": "removed"}

    return api
