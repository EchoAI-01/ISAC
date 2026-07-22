"""Agent 管理端点 (SPECIFICATION.md 4.4)。

待落地: Token 认证依赖注入 + 审计日志 + 统一错误格式。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.runtime.manager import AgentManager


def build_router(agent_manager: AgentManager) -> Any:
    from fastapi import APIRouter, HTTPException

    from isac.core.exceptions import AgentNotFoundError
    from isac.runtime.config import AgentConfig

    router = APIRouter(prefix="/agents", tags=["agents"])

    @router.post("")
    async def create_agent(config: dict) -> dict:
        instance = await agent_manager.create(AgentConfig(**config))
        return {"agent_id": instance.agent_id, "status": instance.status}

    @router.get("")
    async def list_agents() -> list[dict]:
        return [{"agent_id": a.agent_id, "status": a.status} for a in await agent_manager.list()]

    @router.get("/{agent_id}")
    async def get_agent(agent_id: str) -> dict:
        instance = await agent_manager.get(agent_id)
        if instance is None:
            raise HTTPException(status_code=404, detail={"code": "AGENT_NOT_FOUND", "message": agent_id})
        return {"agent_id": instance.agent_id, "status": instance.status}

    @router.post("/{agent_id}/start")
    async def start_agent(agent_id: str) -> dict:
        try:
            await agent_manager.start(agent_id)
        except AgentNotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": exc.code, "message": exc.message}) from exc
        return {"agent_id": agent_id, "status": "running"}

    @router.post("/{agent_id}/stop")
    async def stop_agent(agent_id: str) -> dict:
        try:
            await agent_manager.stop(agent_id)
        except AgentNotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": exc.code, "message": exc.message}) from exc
        return {"agent_id": agent_id, "status": "stopped"}

    @router.delete("/{agent_id}")
    async def destroy_agent(agent_id: str, keep_memory: bool = True) -> dict:
        await agent_manager.destroy(agent_id, keep_memory=keep_memory)
        return {"agent_id": agent_id, "status": "destroyed"}

    return router
