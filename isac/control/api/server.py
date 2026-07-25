"""Admin REST API 服务 (ARCHITECTURE.md 3.9 / SPECIFICATION.md 4.4)。

端点全部委托给 AgentManager / MessageRouter / InterAgentBus / PluginManager。
默认仅监听 127.0.0.1 + Token 认证 (DEVELOP.md 7.4) + 审计日志 (control/audit.py)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.observability.metrics import MetricsCollector
    from isac.observability.usage.storage import UsageStore
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
    metrics: MetricsCollector | None = None,
    usage_store: UsageStore | None = None,
    subagent_supervisor: Any = None,
    provider_manager: Any = None,
    model_catalog: Any = None,
    artifact_store: Any = None,
    session_manager: Any = None,
    metadata_store: Any = None,
    event_bus: Any = None,
) -> Any:
    """创建 FastAPI 应用 (延迟导入 fastapi, 未安装时给出友好错误)。

    config 字段:
    - api_token: Bearer Token (为空时跳过认证, 仅开发模式)
    - agents_dir: AgentConfig 持久化目录 (默认 data/agents)
    - routing_rules_path: 路由规则文件 (默认 data/routing.jsonc)
    - links_path: 互联 Link 文件 (默认 data/links.jsonc)
    - audit_log_path: 审计日志 NDJSON 文件 (默认 data/audit.ndjson)

    metrics: 应用生命周期内唯一的 MetricsCollector 实例 (由 main.build_services()
    创建并注入给核心组件); 未传入时兜底创建独立实例, 保证测试 fixture 不必更新。

    usage_store: J1 用量存储; 为 None (计量未启用) 时不挂载 /usage/models/* 路由,
    404 而不是暴露一个看起来有效但永远空的接口。

    subagent_supervisor: J4 SubAgent 监督器; 为 None (未启用) 时不挂载
    /subagent-runs/* 路由, 404。
    """
    try:
        from fastapi import Depends, FastAPI
    except ImportError as exc:
        raise RuntimeError("控制面需要 fastapi: uv sync --all-extras") from exc

    from isac.control.audit import AuditLog
    from isac.control.auth import (
        make_auth_dependency,
        make_scope_dependency_factory,
        make_token_only_dependency,
        parse_token_scopes,
    )
    from isac.observability import get_default_metrics

    api_token = config.get("api_token", "")
    # Fix-12: control.tokens[] 未配置时 scope_dependency 为 None, 各路由端点的
    # scope 校验整体跳过, 行为与引入本模型之前完全一致 (只有扁平 api_token 认证)。
    parsed_tokens = parse_token_scopes(config)
    scope_dependency = make_scope_dependency_factory(parsed_tokens) if parsed_tokens else None
    # tokens[] 配置生效时, 路由级基线认证必须按 tokens[] 校验 (而不是继续用扁平
    # api_token), 否则任何合法 scoped token 会在到达端点级 scope_dependency 检查
    # 之前就被拒绝 (401) —— 见 make_token_only_dependency 文档字符串。
    if parsed_tokens:
        auth_dependency = make_token_only_dependency(parsed_tokens)
    else:
        auth_dependency = make_auth_dependency(api_token) if api_token else None
    audit_log = AuditLog(log_path=config.get("audit_log_path", "data/audit.ndjson"))
    agents_dir = config.get("agents_dir", "data/agents")
    routing_rules_path = config.get("routing_rules_path", "data/routing.jsonc")
    links_path = config.get("links_path", "data/links.jsonc")
    metrics = metrics or get_default_metrics()

    app = FastAPI(title="ISAC Admin API", version="0.1.0", docs_url="/docs")

    _mount_core_routers(
        app, agent_manager, router, bus, plugin_manager, config,
        auth_dependency, audit_log, agents_dir, routing_rules_path, links_path,
        scope_dependency,
    )
    _mount_optional_routers(
        app, usage_store, subagent_supervisor, provider_manager, model_catalog,
        artifact_store, session_manager, metadata_store, event_bus, auth_dependency,
        scope_dependency, parsed_tokens,
    )

    audit_deps = [Depends(auth_dependency)] if auth_dependency else []

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/v1/audit", dependencies=audit_deps)
    async def query_audit(
        action: str | None = None,
        actor: str | None = None,
        path_prefix: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return audit_log.query(action=action, actor=actor, path_prefix=path_prefix, limit=limit)

    @app.get("/metrics")
    async def prometheus_metrics() -> Any:
        """Prometheus 文本格式 (供 Prometheus 抓取, 不需认证)。"""
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(metrics.to_prometheus(), media_type="text/plain")

    @app.get("/api/v1/metrics", dependencies=audit_deps)
    async def metrics_snapshot() -> dict:
        """JSON 指标快照 (供 WebUI 或监控系统集成, 需认证)。"""
        return metrics.snapshot()

    # I1: 挂载 WebUI 管理面板 (Vanilla JS, 不依赖 Vue 构建工具链)
    try:
        from isac.control.webui import mount_webui

        mount_webui(app, prefix="/ui", api_token=api_token)
    except Exception as exc:  # noqa: BLE001
        # WebUI 挂载失败不阻塞 API
        from isac.utils.logger import get_logger as _get_logger

        _get_logger(__name__).warning("WebUI 挂载失败", error=str(exc))

    return app


def _mount_core_routers(
    app: Any,
    agent_manager: AgentManager,
    router: MessageRouter,
    bus: InterAgentBus,
    plugin_manager: PluginManager,
    config: dict[str, Any],
    auth_dependency: Any,
    audit_log: Any,
    agents_dir: str,
    routing_rules_path: str,
    links_path: str,
    scope_dependency: Any = None,
) -> None:
    """挂载核心路由 (agents / routing / plugins)。"""
    from isac.control.api import routes_agents, routes_plugins, routes_routing

    app.include_router(
        routes_agents.build_router(
            agent_manager,
            auth_dependency=auth_dependency,
            audit_log=audit_log,
            agents_dir=agents_dir,
            scope_dependency=scope_dependency,
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
            scope_dependency=scope_dependency,
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
            scope_dependency=scope_dependency,
        ),
        prefix="/api/v1",
    )


def _mount_optional_routers(
    app: Any,
    usage_store: Any,
    subagent_supervisor: Any,
    provider_manager: Any,
    model_catalog: Any,
    artifact_store: Any,
    session_manager: Any,
    metadata_store: Any,
    event_bus: Any,
    auth_dependency: Any,
    scope_dependency: Any = None,
    tokens: Any = None,
) -> None:
    """挂载可选路由 (usage / subagent / providers / config / sessions / memory / events)。"""
    if usage_store is not None:
        from isac.control.api import routes_usage

        app.include_router(
            routes_usage.build_router(
                usage_store, auth_dependency=auth_dependency, scope_dependency=scope_dependency,
            ),
            prefix="/api/v1",
        )
    if subagent_supervisor is not None:
        from isac.control.api import routes_subagent

        app.include_router(
            routes_subagent.build_router(
                subagent_supervisor, auth_dependency=auth_dependency, scope_dependency=scope_dependency,
            ),
            prefix="/api/v1",
        )
    if provider_manager is not None and model_catalog is not None:
        from isac.control.api import routes_providers

        app.include_router(
            routes_providers.build_router(
                provider_manager, model_catalog, artifact_store,
                auth_dependency=auth_dependency, scope_dependency=scope_dependency,
            ),
            prefix="/api/v1",
        )
    # J3-2: 配置编辑事务路由 (无条件挂载; validate/diff 不依赖外部服务)
    from isac.control.api import routes_config

    app.include_router(
        routes_config.build_router(auth_dependency=auth_dependency),
        prefix="/api/v1",
    )
    # J3-3: Sessions 路由 (session_manager 注入时挂载)
    if session_manager is not None:
        from isac.control.api import routes_sessions

        app.include_router(
            routes_sessions.build_router(session_manager, metadata_store, auth_dependency=auth_dependency),
            prefix="/api/v1",
        )
    # J3-3: Memory 路由 (metadata_store 注入时挂载; 无则返回 None 不挂载)
    from isac.control.api import routes_memory

    memory_router = routes_memory.build_router(metadata_store, auth_dependency=auth_dependency)
    if memory_router is not None:
        app.include_router(memory_router, prefix="/api/v1")
    # J3-4: Events SSE 路由 (event_bus 注入时挂载)
    if event_bus is not None:
        from isac.control.api import routes_events

        app.include_router(
            routes_events.build_router(event_bus, auth_dependency=auth_dependency, tokens=tokens),
            prefix="/api/v1",
        )
