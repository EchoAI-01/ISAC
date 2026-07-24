"""Agent 管理端点 (SPECIFICATION.md 4.4)。

Bearer Token 认证 (依赖注入) + 审计日志 (写操作记录) + AgentConfig 持久化到 data/agents/<id>/config.jsonc。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.control.audit import AuditLog
    from isac.runtime.manager import AgentManager


def build_router(
    agent_manager: AgentManager,
    auth_dependency: Any = None,
    audit_log: AuditLog | None = None,
    agents_dir: str = "data/agents",
) -> Any:
    from fastapi import APIRouter, Depends, HTTPException

    from isac.runtime.config import save_agent_config

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(prefix="/agents", tags=["agents"], dependencies=deps)
    # agents_dir 是配置传入的字符串, 统一规范化为 Path 后续拼接都用 / 操作符,
    # 避免字符串拼接绕开 AgentConfig.__post_init__ 对 agent_id 的格式校验
    # (CODE_REVIEW_REPORT.md #19)。
    agents_dir_path = Path(agents_dir)

    @router.post("")
    async def create_agent(config: dict) -> dict:
        instance = await _do_create_agent(agent_manager, config)
        # Path / 操作符自然处理分隔符; agent_id 已由 AgentConfig 校验只含 [A-Za-z0-9_-]
        config_path = agents_dir_path / instance.agent_id / "config.jsonc"
        save_agent_config(config_path, instance.config)
        await _audit(
            audit_log, "POST", "/api/v1/agents", "create_agent", instance.agent_id
        )
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
        await _require_agent(agent_manager, agent_id, "start")
        await _audit(audit_log, "POST", f"/api/v1/agents/{agent_id}/start", "start_agent", agent_id)
        return {"agent_id": agent_id, "status": "running"}

    @router.post("/{agent_id}/stop")
    async def stop_agent(agent_id: str) -> dict:
        await _require_agent(agent_manager, agent_id, "stop")
        await _audit(audit_log, "POST", f"/api/v1/agents/{agent_id}/stop", "stop_agent", agent_id)
        return {"agent_id": agent_id, "status": "stopped"}

    @router.delete("/{agent_id}")
    async def destroy_agent(agent_id: str, keep_memory: bool = True) -> dict:
        await _require_agent(agent_manager, agent_id, "destroy")
        await agent_manager.destroy(agent_id, keep_memory=keep_memory)
        await _audit(
            audit_log, "DELETE", f"/api/v1/agents/{agent_id}", "destroy_agent",
            agent_id, detail=f"keep_memory={keep_memory}",
        )
        return {"agent_id": agent_id, "status": "destroyed"}

    return router


async def _do_create_agent(agent_manager: AgentManager, config: dict) -> Any:
    """构造 AgentConfig 并创建实例, 错误转 HTTPException。

    构造 AgentConfig (格式校验，如 agent_id 非法) 与创建实例 (是否已存在) 分开处理，
    避免 agent_id 格式错误被误报成"已存在" (409)。
    """
    from fastapi import HTTPException

    from isac.runtime.config import AgentConfig

    try:
        agent_config = AgentConfig(**config)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_CONFIG", "message": str(exc)}) from exc

    try:
        return await agent_manager.create(agent_config)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "AGENT_EXISTS", "message": str(exc)}) from exc


async def _require_agent(agent_manager: AgentManager, agent_id: str, action: str) -> None:
    """执行需要 Agent 存在的操作 (start/stop/destroy); 不存在抛 404。"""
    from fastapi import HTTPException

    from isac.core.exceptions import AgentNotFoundError
    try:
        if action == "start":
            await agent_manager.start(agent_id)
        elif action == "stop":
            await agent_manager.stop(agent_id)
        elif action == "destroy":
            # destroy 内部会自己 _require, 这里只是 placeholder 保持接口一致
            return
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": exc.message}) from exc


async def _audit(
    audit_log: AuditLog | None,
    method: str,
    path: str,
    action: str,
    target: str,
    detail: str = "",
) -> None:
    """记录审计日志 (如果 audit_log 为 None 则跳过)。"""
    if audit_log is None:
        return
    await audit_log.record(
        actor="authenticated",
        method=method,
        path=path,
        action=action,
        target=target,
        detail=detail,
        status_code=200,
    )
