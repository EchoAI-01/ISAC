"""插件启用矩阵端点 (SPECIFICATION.md 4.4)。

TODO(Day 73): Token 认证 + 矩阵持久化到 AgentConfig + 审计日志。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.plugin.runtime.manager import PluginManager
    from isac.runtime.manager import AgentManager


def build_router(agent_manager: AgentManager, plugin_manager: PluginManager) -> Any:
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/agents/{agent_id}/plugins", tags=["plugins"])

    @router.get("")
    async def get_matrix(agent_id: str) -> dict:
        instance = await agent_manager.get(agent_id)
        if instance is None:
            raise HTTPException(status_code=404, detail={"code": "AGENT_NOT_FOUND", "message": agent_id})
        return {
            "plugins_allow": instance.config.plugins_allow,
            "plugins_deny": instance.config.plugins_deny,
        }

    @router.put("")
    async def put_matrix(agent_id: str, body: dict) -> dict:
        instance = await agent_manager.get(agent_id)
        if instance is None:
            raise HTTPException(status_code=404, detail={"code": "AGENT_NOT_FOUND", "message": agent_id})
        instance.config.plugins_allow = list(body.get("plugins_allow", ["*"]))
        instance.config.plugins_deny = list(body.get("plugins_deny", []))
        # TODO(Day 73): 持久化到 data/agents/<id>/config.jsonc
        return {"status": "updated"}

    return router
