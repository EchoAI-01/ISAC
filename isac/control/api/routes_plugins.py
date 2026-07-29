"""插件启用矩阵端点 (SPECIFICATION.md 4.4) + 已加载插件列表 (Q5 激活)。

Bearer Token 认证 + 矩阵持久化到 AgentConfig + 审计日志。
Q5: GET /plugins/loaded 列出 PluginManager.list_loaded() 的全部已加载插件,
替代 WebUI 此前的占位假数据。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.control.audit import AuditLog
    from isac.plugin.runtime.manager import PluginManager
    from isac.runtime.manager import AgentManager


def build_router(
    agent_manager: AgentManager,
    plugin_manager: PluginManager,
    auth_dependency: Any = None,
    audit_log: AuditLog | None = None,
    agents_dir: str = "data/agents",
    scope_dependency: Any = None,
) -> Any:
    from fastapi import APIRouter, Depends, HTTPException

    from isac.runtime.config import save_agent_config

    router = APIRouter(
        prefix="/agents/{agent_id}/plugins",
        tags=["plugins"],
        dependencies=[Depends(auth_dependency)] if auth_dependency else [],
    )
    write_deps = [Depends(scope_dependency("plugin:write"))] if scope_dependency else []

    @router.get("")
    async def get_matrix(agent_id: str) -> dict:
        instance = await agent_manager.get(agent_id)
        if instance is None:
            raise HTTPException(status_code=404, detail={"code": "AGENT_NOT_FOUND", "message": agent_id})
        return {
            "plugins_allow": instance.config.plugins_allow,
            "plugins_deny": instance.config.plugins_deny,
        }

    @router.put("", dependencies=write_deps)
    async def put_matrix(agent_id: str, body: dict) -> dict:
        instance = await agent_manager.get(agent_id)
        if instance is None:
            raise HTTPException(status_code=404, detail={"code": "AGENT_NOT_FOUND", "message": agent_id})
        instance.config.plugins_allow = list(body.get("plugins_allow", ["*"]))
        instance.config.plugins_deny = list(body.get("plugins_deny", []))
        # 持久化到 data/agents/<id>/config.jsonc
        save_agent_config(Path(agents_dir) / agent_id / "config.jsonc", instance.config)
        if audit_log is not None:
            await audit_log.record(
                actor="authenticated",
                method="PUT",
                path=f"/api/v1/agents/{agent_id}/plugins",
                action="update_plugin_matrix",
                target=agent_id,
                detail=f"allow={len(instance.config.plugins_allow)}/deny={len(instance.config.plugins_deny)}",
                status_code=200,
            )
        return {"status": "updated"}

    return router


def build_loaded_plugins_router(
    plugin_manager: PluginManager,
    auth_dependency: Any = None,
    scope_dependency: Any = None,
) -> Any:
    """Q5: 已加载插件列表路由 GET /plugins/loaded。

    WebUI 插件页此前用占位假数据 ("(插件 API 待实现)"), 现经此端点读取
    PluginManager.list_loaded() 的真实已加载插件名列表。
    """
    from fastapi import APIRouter, Depends

    router = APIRouter(
        prefix="/plugins",
        tags=["plugins"],
        dependencies=[Depends(auth_dependency)] if auth_dependency else [],
    )
    read_deps = [Depends(scope_dependency("plugin:read"))] if scope_dependency else []

    @router.get("/loaded", dependencies=read_deps)
    async def list_loaded() -> dict:
        # list_loaded 同时含宿主进程内 + 隔离子进程的插件名
        loaded = plugin_manager.list_loaded()
        # 附带每个插件是否以隔离方式加载 (供 WebUI 区分)
        items = [
            {
                "name": name,
                "isolated": plugin_manager.is_isolated(name),
            }
            for name in loaded
        ]
        return {"plugins": items, "total": len(items)}

    return router
