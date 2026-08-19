"""插件启用矩阵端点 (SPECIFICATION.md 4.4) + 已加载插件列表 (Q5 激活)。

Bearer Token 认证 + 矩阵持久化到 AgentConfig + 审计日志。
Q5: GET /plugins/loaded 列出 PluginManager.list_loaded() 的全部已加载插件,
替代 WebUI 此前的占位假数据。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from isac.plugin.runtime.activation import activate_plugin, sync_plugin_tools_to_agents

if TYPE_CHECKING:
    from isac.control.audit import AuditLog
    from isac.plugin.runtime.installer import PluginInstaller
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
    # #29 审计 actor 归因: handler 经此依赖拿真实调用方身份写入审计。
    caller_dep = Depends(auth_dependency) if auth_dependency else Depends(lambda: "anonymous")

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
    async def put_matrix(agent_id: str, body: dict, caller: str = caller_dep) -> dict:
        # Fix-59: get + 404 判断挪进配置锁内 —— 此前锁外取 instance, 而
        # reload_config 会整体替换 _agents[agent_id] 的实例对象: 锁外取到旧
        # 实例 → 并发 PATCH 先完成 (live 换新实例, revision+1) → 本端点进锁改
        # 旧实例并以其 config 写盘 → 矩阵改动落不到 live 实例 + 盘上其他字段
        # 被陈旧值覆盖 (与 _do_patch_agent 的"先进锁后 get"不对称)。
        async with agent_manager.acquire_config_lock(agent_id):
            instance = await agent_manager.get(agent_id)
            if instance is None:
                raise HTTPException(status_code=404, detail={"code": "AGENT_NOT_FOUND", "message": agent_id})
            instance.config.plugins_allow = _as_str_list(body.get("plugins_allow", ["*"]))
            instance.config.plugins_deny = _as_str_list(body.get("plugins_deny", []))
            # 持久化到 data/agents/<id>/config.jsonc
            save_agent_config(Path(agents_dir) / agent_id / "config.jsonc", instance.config)
        if audit_log is not None:
            await audit_log.record(
                actor=caller,
                method="PUT",
                path=f"/api/v1/agents/{agent_id}/plugins",
                action="update_plugin_matrix",
                target=agent_id,
                detail=f"allow={len(instance.config.plugins_allow)}/deny={len(instance.config.plugins_deny)}",
                status_code=200,
            )
        return {"status": "updated"}

    return router


def _as_str_list(value: Any) -> list[str]:
    """Fix-48: 把 body 里的 allow/deny 规范化为 str list。

    此前 ``list(value)`` 对字符串输入会逐字符拆开 (如 ``"abc"`` → ``["a","b","c"]``),
    无类型校验。list 原样保留 (逐项转 str), 单值包成单元素 list, 其余视为空。
    """
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []


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


async def _audit_record(
    audit_log: AuditLog | None, action: str, target: str, detail: str, status_code: int,
    actor: str = "authenticated",
) -> None:
    """记录插件操作审计日志 (审计为 None 时 no-op)。actor 归因 (#29)。"""
    if audit_log is not None:
        await audit_log.record(
            actor=actor,
            method="POST",
            path=f"/api/v1/plugins/{target}",
            action=action,
            target=target,
            detail=detail,
            status_code=status_code,
        )


def _client_error_message(exc: Exception) -> str:
    """Fix-110: 插件操作失败时控制返回客户端的错误信息, 不回显内部细节。

    ValueError 是 installer/manager 显式抛出的受控校验/安全错误 (安装源缺 name /
    SSRF 拒绝 / zip 解码失败等), 消息经人工审定可原样返回; 其余异常 (git clone 的
    stderr、文件系统/网络堆栈等) 可能含路径/URL/凭据, 返回通用消息, 明细留给服务端
    审计 (上方 _audit_record 已落 ``failed: {exc}``) 与日志。对齐全局异常处理器
    "客户端只返回通用消息不泄露内部信息" 的口径。
    """
    if isinstance(exc, ValueError):
        return str(exc)
    return "插件操作内部错误, 详见服务端日志"


async def _activate_and_sync(
    plugin_manager: Any,
    agent_manager: Any,
    services: dict[str, Any],
    name: str,
    *,
    event_bus: Any,
    bus: Any,
    router: Any,
) -> dict[str, list[str]]:
    """激活单个插件 + 同步共享表变更到运行中 Agent (T6 热重载核心路径)。"""
    await activate_plugin(plugin_manager, name, services, event_bus=event_bus, bus=bus, router=router)
    return await sync_plugin_tools_to_agents(agent_manager, services, name)


async def _handle_install(
    plugin_manager: Any, agent_manager: Any, installer: Any, services: dict[str, Any],
    source: dict[str, Any], *, event_bus: Any, bus: Any, router: Any, audit_log: AuditLog | None,
    actor: str = "authenticated",
) -> dict[str, Any]:
    from fastapi import HTTPException

    name = source.get("name", "")
    try:
        status = await plugin_manager.install(source, installer)
    except Exception as exc:  # noqa: BLE001
        await _audit_record(audit_log, "install_plugin", name, f"failed: {exc}", 400, actor=actor)
        raise HTTPException(
            status_code=400, detail={"code": "INSTALL_FAILED", "message": _client_error_message(exc)}
        ) from exc
    sync_result: dict[str, list[str]] = {}
    if name and not status.startswith("failed"):
        sync_result = await _activate_and_sync(
            plugin_manager, agent_manager, services, name, event_bus=event_bus, bus=bus, router=router
        )
    await _audit_record(audit_log, "install_plugin", name, f"status={status}", 200, actor=actor)
    return {"status": status, "sync": sync_result}


def _deregister_shared_by_source(services: dict[str, Any], name: str, event_bus: Any = None) -> None:
    """C2: 从进程级共享注册表移除该插件来源的全部条目 (工具/命令/注入器/钩子/事件订阅)。

    reload 前清旧条目避免 activate 后新旧同名残留; uninstall 后清空让 sync 精确模式
    把 per-Agent 对应条目也清掉。event_bus 为顶层共享 (非 services 键), 单独传。
    """
    for key in ("plugin_tools", "plugin_commands", "plugin_prompt_builder", "plugin_agent_hooks"):
        reg = services.get(key)
        if reg is not None and hasattr(reg, "deregister_by_source"):
            reg.deregister_by_source(name)
    if event_bus is not None and hasattr(event_bus, "deregister_by_source"):
        event_bus.deregister_by_source(name)


async def _handle_reload(
    plugin_manager: Any, agent_manager: Any, services: dict[str, Any], name: str,
    *, event_bus: Any, bus: Any, router: Any, audit_log: AuditLog | None,
    actor: str = "authenticated",
) -> dict[str, Any]:
    from fastapi import HTTPException

    # 1. C2: 从共享表移除该插件全部来源条目 (工具/命令/注入器/钩子/事件订阅, 非仅工具),
    #    避免 activate 后旧的不同名条目残留 (此前只清 tools, 命令/注入器/钩子/事件残留)。
    _deregister_shared_by_source(services, name, event_bus)
    # 2. PluginManager reload (unload + 重新 load_entry)
    try:
        status = await plugin_manager.reload(name)
    except Exception as exc:  # noqa: BLE001
        await _audit_record(audit_log, "reload_plugin", name, f"failed: {exc}", 500, actor=actor)
        raise HTTPException(
            status_code=500, detail={"code": "RELOAD_FAILED", "message": _client_error_message(exc)}
        ) from exc
    if status in ("not_loaded", "not_found"):
        raise HTTPException(status_code=404, detail={"code": "PLUGIN_NOT_FOUND", "message": status})
    if status.startswith("failed"):
        raise HTTPException(status_code=500, detail={"code": "RELOAD_FAILED", "message": status})
    # 3. 激活 (on_load/adapt) + 4. 同步运行中 Agent registry
    sync_result = await _activate_and_sync(
        plugin_manager, agent_manager, services, name, event_bus=event_bus, bus=bus, router=router
    )
    await _audit_record(audit_log, "reload_plugin", name, f"status={status}", 200, actor=actor)
    return {"status": status, "sync": sync_result}


async def _handle_uninstall(
    plugin_manager: Any, agent_manager: Any, services: dict[str, Any], name: str,
    *, event_bus: Any = None, bus: Any = None, router: Any = None, audit_log: AuditLog | None,
    actor: str = "authenticated",
) -> dict[str, Any]:
    # C2: 从共享表 + 运行中 Agent 移除该插件全部来源条目 (工具/命令/注入器/钩子/事件订阅)
    _deregister_shared_by_source(services, name, event_bus)
    status = await plugin_manager.uninstall(name)
    sync_result = await sync_plugin_tools_to_agents(agent_manager, services, name)
    await _audit_record(audit_log, "uninstall_plugin", name, f"status={status}", 200, actor=actor)
    return {"status": status, "sync": sync_result}


async def _handle_retry(
    plugin_manager: Any, agent_manager: Any, services: dict[str, Any], name: str,
    *, event_bus: Any, bus: Any, router: Any, audit_log: AuditLog | None,
    actor: str = "authenticated",
) -> dict[str, Any]:
    from fastapi import HTTPException

    try:
        status = await plugin_manager.retry(name)
    except Exception as exc:  # noqa: BLE001
        await _audit_record(audit_log, "retry_plugin", name, f"failed: {exc}", 500, actor=actor)
        raise HTTPException(
            status_code=500, detail={"code": "RETRY_FAILED", "message": _client_error_message(exc)}
        ) from exc
    sync_result: dict[str, list[str]] = {}
    if not status.startswith("failed"):
        sync_result = await _activate_and_sync(
            plugin_manager, agent_manager, services, name, event_bus=event_bus, bus=bus, router=router
        )
    await _audit_record(audit_log, "retry_plugin", name, f"status={status}", 200, actor=actor)
    return {"status": status, "sync": sync_result}


def build_plugin_marketplace_router(
    plugin_manager: PluginManager,
    agent_manager: AgentManager,
    installer: PluginInstaller,
    services: dict[str, Any],
    *,
    event_bus: Any = None,
    bus: Any = None,
    router: Any = None,
    auth_dependency: Any = None,
    scope_dependency: Any = None,
    audit_log: AuditLog | None = None,
    allow_install: bool = True,
) -> Any:
    """T6: 插件市场 + 安装 + 热重载 + 卸载 + 失败重试路由。

    前缀 /plugins, 写操作需 plugin:write scope + 审计日志。allow_install=False 时
    只注册读端点 (marketplace/failed), 不注册写端点 (减少攻击面)。端点逻辑抽到
    模块级 _handle_* 辅助以控制本函数复杂度。
    """
    from fastapi import APIRouter, Depends

    api = APIRouter(
        prefix="/plugins",
        tags=["plugins"],
        dependencies=[Depends(auth_dependency)] if auth_dependency else [],
    )
    read_deps = [Depends(scope_dependency("plugin:read"))] if scope_dependency else []
    write_deps = [Depends(scope_dependency("plugin:write"))] if scope_dependency else []

    @api.get("/marketplace", dependencies=read_deps)
    async def list_marketplace(refresh: bool = False) -> dict:
        entries = await installer.load_marketplace(refresh=refresh)
        return {"plugins": entries, "total": len(entries)}

    @api.get("/failed", dependencies=read_deps)
    async def list_failed() -> dict:
        failures = plugin_manager.list_failures()
        return {"failures": failures, "total": len(failures)}

    if not allow_install:
        return api

    kw = {"event_bus": event_bus, "bus": bus, "router": router, "audit_log": audit_log}

    # #29 审计 actor 归因: handler 经此依赖拿真实调用方身份写入审计。
    caller_dep = Depends(auth_dependency) if auth_dependency else Depends(lambda: "anonymous")

    @api.post("/install", dependencies=write_deps)
    async def install_plugin(body: dict, caller: str = caller_dep) -> dict:
        source = body.get("source", body) if isinstance(body, dict) else {}
        return await _handle_install(
            plugin_manager, agent_manager, installer, services, source, actor=caller, **kw
        )

    @api.post("/{name}/reload", dependencies=write_deps)
    async def reload_plugin(name: str, caller: str = caller_dep) -> dict:
        return await _handle_reload(plugin_manager, agent_manager, services, name, actor=caller, **kw)

    @api.delete("/{name}", dependencies=write_deps)
    async def uninstall_plugin(name: str, caller: str = caller_dep) -> dict:
        return await _handle_uninstall(plugin_manager, agent_manager, services, name, actor=caller, **kw)

    @api.post("/{name}/retry", dependencies=write_deps)
    async def retry_plugin(name: str, caller: str = caller_dep) -> dict:
        return await _handle_retry(plugin_manager, agent_manager, services, name, actor=caller, **kw)

    return api
