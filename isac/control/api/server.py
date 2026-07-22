"""Admin REST API 服务 (ARCHITECTURE.md 3.9 / SPECIFICATION.md 4.4)。

端点全部委托给 AgentManager / MessageRouter / InterAgentBus / PluginManager。
默认仅监听 127.0.0.1 + Token 认证 (DEVELOP.md 7.4) + 审计日志 (control/audit.py)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.plugin.runtime.manager import PluginManager
    from isac.router.router import MessageRouter
    from isac.runtime.bus import InterAgentBus
    from isac.runtime.manager import AgentManager


def create_control_app(
    agent_manager: AgentManager,
    router: MessageRouter,
    bus: InterAgentBus,
    plugin_manager: PluginManager,
    config: dict[str, Any],
) -> Any:
    """创建 FastAPI 应用 (延迟导入 fastapi, 未安装时给出友好错误)。

    config 字段:
    - api_token: Bearer Token (为空时跳过认证, 仅开发模式)
    - agents_dir: AgentConfig 持久化目录 (默认 data/agents)
    - routing_rules_path: 路由规则文件 (默认 data/routing.jsonc)
    - links_path: 互联 Link 文件 (默认 data/links.jsonc)
    - audit_log_path: 审计日志 NDJSON 文件 (默认 data/audit.ndjson)
    """
    try:
        from fastapi import FastAPI
    except ImportError as exc:
        raise RuntimeError("控制面需要 fastapi: uv sync --all-extras") from exc

    from isac.control.api import routes_agents, routes_plugins, routes_routing
    from isac.control.audit import AuditLog
    from isac.control.auth import make_auth_dependency

    api_token = config.get("api_token", "")
    auth_dependency = make_auth_dependency(api_token) if api_token else None
    audit_log = AuditLog(log_path=config.get("audit_log_path", "data/audit.ndjson"))
    agents_dir = config.get("agents_dir", "data/agents")
    routing_rules_path = config.get("routing_rules_path", "data/routing.jsonc")
    links_path = config.get("links_path", "data/links.jsonc")

    app = FastAPI(title="ISAC Admin API", version="0.1.0", docs_url="/docs")

    app.include_router(
        routes_agents.build_router(
            agent_manager,
            auth_dependency=auth_dependency,
            audit_log=audit_log,
            agents_dir=agents_dir,
        ),
        prefix="/api/v1",
    )
    app.include_router(
        routes_routing.build_router(
            router,
            bus,
            auth_dependency=auth_dependency,
            audit_log=audit_log,
            routing_rules_path=routing_rules_path,
            links_path=links_path,
        ),
        prefix="/api/v1",
    )
    app.include_router(
        routes_plugins.build_router(
            agent_manager,
            plugin_manager,
            auth_dependency=auth_dependency,
            audit_log=audit_log,
            agents_dir=agents_dir,
        ),
        prefix="/api/v1",
    )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/v1/audit")
    async def query_audit(
        action: str | None = None,
        actor: str | None = None,
        path_prefix: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return audit_log.query(action=action, actor=actor, path_prefix=path_prefix, limit=limit)

    # I1: 挂载 WebUI 管理面板 (Vanilla JS, 不依赖 Vue 构建工具链)
    try:
        from isac.control.webui import mount_webui

        mount_webui(app, prefix="/ui", api_token=api_token)
    except Exception as exc:  # noqa: BLE001
        # WebUI 挂载失败不阻塞 API
        from isac.utils.logger import get_logger as _get_logger

        _get_logger(__name__).warning("WebUI 挂载失败", error=str(exc))

    return app
