"""Admin REST API 服务 (ARCHITECTURE.md 3.9 / SPECIFICATION.md 4.4)。

端点全部委托给 AgentManager / MessageRouter / InterAgentBus / PluginManager。
默认仅监听 127.0.0.1 + Token 认证 (DEVELOP.md 7.4)。
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
    """创建 FastAPI 应用 (延迟导入 fastapi，未安装时给出友好错误)。

    TODO(Day 71-73): 注册全部路由 + Token 认证中间件 + 审计日志。
    """
    try:
        from fastapi import FastAPI
    except ImportError as exc:
        raise RuntimeError("控制面需要 fastapi: uv sync --all-extras") from exc

    app = FastAPI(title="ISAC Admin API", version="0.1.0", docs_url="/docs")

    from isac.control.api import routes_agents, routes_plugins, routes_routing

    app.include_router(routes_agents.build_router(agent_manager), prefix="/api/v1")
    app.include_router(routes_routing.build_router(router, bus), prefix="/api/v1")
    app.include_router(routes_plugins.build_router(agent_manager, plugin_manager), prefix="/api/v1")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
