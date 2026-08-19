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


def _warn_if_no_auth(api_token: str, parsed_tokens: Any) -> bool:
    """R4: 控制面已启用但无认证时 CRITICAL 警告 (不阻止启动, 保 dev 模式兼容)。

    create_control_app 被调用即意味着 control.enabled=true, 若 api_token 与
    tokens[] 均空, 所有 admin 端点 (config edit / plugin load / memory admin /
    agent create) 全部无认证暴露。生产部署应配 token 或加网络层防护。

    返回 True 表示触发了 CRITICAL 警告, False 表示有认证 (early return)。
    """
    if api_token or parsed_tokens:
        return False
    from isac.utils.logger import get_logger as _get_logger
    _get_logger(__name__).critical(
        "control plane enabled but api_token and tokens[] both empty; "
        "all admin endpoints are unauthenticated (config edit / plugin load / "
        "memory admin / agent create etc.). Configure control.api_token or "
        "control.tokens[] in production."
    )
    return True


def _register_global_exception_handler(app: Any) -> None:
    """R14: 全局 exception handler 兜底未捕获异常。

    服务端 exc_info=True 记录完整堆栈, 客户端只返回通用 "internal error"
    不泄露 Python 类型/字段路径/磁盘 IO 信息。HTTPException 由 FastAPI 默认
    处理 (保留 status code 和 detail, 各路由已把 detail.message 改通用消息)。
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse

    from isac.utils.logger import get_logger as _get_logger

    _global_logger = _get_logger(__name__)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        _global_logger.error(
            "Control API 未捕获异常",
            path=str(request.url.path),
            method=request.method,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": {"code": "INTERNAL_ERROR", "message": "Internal server error"}},
        )


def _configure_cors(app: Any, config: dict[str, Any]) -> list[str]:
    """FE1: CORS 策略 (前后端分离)。origins 非空时加 CORSMiddleware 放开跨源。

    返回 cors_origins 供调用方决定 Session Cookie 的 SameSite (非空=lax 跨源可带,
    空=strict 同源)。生产推荐同源反代 (前端与 API 同 origin), 无需配置本字段。
    """
    cors_cfg = config.get("cors") or {}
    cors_origins = list(cors_cfg.get("origins") or [])
    if cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=bool(cors_cfg.get("allow_credentials", True)),
            allow_methods=["*"],
            allow_headers=["*"],
        )
    return cors_origins


def _build_setup_manager(config: dict[str, Any]) -> Any:
    """T3-backend: 按 config.setup_enabled 构造 SetupManager (默认 None 向后兼容)。

    setup_enabled 默认 False (不破坏无凭证的旧测试); config.sample.jsonc 的
    control.setup_enabled=true 让开箱首登强制设密码。

    Fix-40: 传入 static_credentials_configured —— 已配 api_token/tokens 时 setup
    通道关闭 (POST /setup 拒绝), 防未认证攻击者经 setup 设密码接管控制面。
    """
    if not config.get("setup_enabled", False):
        return None
    from isac.control.auth import parse_token_scopes
    from isac.control.setup import SetupManager

    # Fix-61: 与 auth 层实际判定对齐 —— parse_token_scopes 对"tokens 非空但
    # 全部缺 token 字段"返回 None (合法回退态, 视为未配置)。此前标志用原始
    # 真值 bool(config.get("tokens")), 该误配下 POST /setup 被 403 拒绝而
    # auth 又走"无凭证"分支全端点 401 且无 428 引导 → 控制面完全锁死。
    has_static = bool(config.get("api_token")) or parse_token_scopes(config) is not None
    return SetupManager(
        config.get("setup_state_path", "data/control/setup_state.json"),
        static_credentials_configured=has_static,
    )


def _mount_session_auth(
    app: Any, api_token: str, parsed_tokens: Any, session_secret: bytes | None, session_samesite: str
) -> None:
    """Fix-17: session_secret 非 None 时挂 CSRF middleware + /auth/session 路由。

    CSRF 只对靠会话 Cookie 认证的写请求生效, 纯 Bearer Header 的 API 客户端不受影响。
    """
    if session_secret is None:
        return
    from isac.control.auth import CSRFProtectionMiddleware

    app.add_middleware(CSRFProtectionMiddleware)
    from isac.control.api import routes_auth

    app.include_router(
        routes_auth.build_router(
            api_token, parsed_tokens, session_secret, samesite=session_samesite,
        ),
        prefix="/api/v1",
    )


def _mount_setup_router(app: Any, setup_manager: Any) -> None:
    """T3-backend: setup_manager 非 None 时挂 /setup 路由 (首登态也要可达)。"""
    if setup_manager is None:
        return
    from isac.control.api import routes_setup

    app.include_router(routes_setup.build_router(setup_manager), prefix="/api/v1")


def _build_auth_dependency(
    api_token: str, parsed_tokens: Any, session_secret: bytes | None, setup_manager: Any
) -> Any:
    """T3-backend: 构造路由级认证依赖 (抽 helper 降低 create_control_app 圈复杂度)。

    tokens[] 优先 → make_token_only_dependency; api_token 次 → make_auth_dependency;
    都无 → make_auth_dependency("", ..., setup_manager): setup_manager 决定首登态
    428 或纯开发模式 anonymous。setup_manager=None 时与引入 T3 前行为一致。
    """
    from isac.control.auth import make_auth_dependency, make_token_only_dependency

    if parsed_tokens:
        return make_token_only_dependency(parsed_tokens, session_secret, setup_manager)
    if api_token:
        return make_auth_dependency(api_token, session_secret, setup_manager)
    return make_auth_dependency("", session_secret, setup_manager)


def _aggregate_health(
    agent_manager: Any,
    provider_manager: Any,
    config: dict[str, Any],
    channel_registry: Any,
) -> dict[str, Any]:
    """T4: 聚合各子系统状态供 /health 返回 (抽 helper 避免 create_control_app C901)。

    各子系统用 getattr 防御: 旧测试替身/未注入的 manager 可能缺方法。任一关键
    子系统异常 → status=degraded; 否则 ok。引用真实配置路径让用户知道去哪修。
    """
    # agents: running/total
    agents_total = agents_running = 0
    list_agents = getattr(agent_manager, "list", None)
    if callable(list_agents):
        try:
            instances = list_agents()
            agents_total = len(instances)
            agents_running = sum(1 for a in instances if getattr(a, "status", "") == "running")
        except Exception:  # noqa: BLE001
            pass

    # llm: provider 是否 stub (未配置真实 key 的引导态)
    llm_status = "unknown"
    pm_list = getattr(provider_manager, "list_providers", None) if provider_manager else None
    if callable(pm_list):
        try:
            providers = pm_list()
            # 检测是否含 StubProvider (T1: 未配置有效 key 时为 stub)
            has_stub = any(type(p).__name__ == "StubProvider" for p in providers)
            llm_status = "stub" if has_stub and len(providers) >= 1 else "configured"
        except Exception:  # noqa: BLE001
            pass
    elif provider_manager is None:
        llm_status = "not_configured"

    # channels: 已注册平台列表
    channels: list[str] = []
    if channel_registry is not None:
        list_ch = getattr(channel_registry, "list", None)
        if callable(list_ch):
            try:
                channels = [getattr(a, "platform_name", "?") for a in list_ch()]
            except Exception:  # noqa: BLE001
                pass

    control_cfg = config or {}
    degraded = agents_total == 0 and not channels  # 无 Agent 且无 Channel → 不可用
    return {
        "status": "degraded" if degraded else "ok",
        "subsystems": {
            "agents": {"total": agents_total, "running": agents_running},
            "llm": llm_status,
            "channels": channels,
            "control": {
                "enabled": bool(control_cfg.get("enabled")),
                "host": control_cfg.get("host", "127.0.0.1"),
                "port": control_cfg.get("port", 8765),
            },
        },
    }


def _audit_read_deps(auth_dependency: Any, scope_dependency: Any) -> list[Any]:
    """Fix-107: /api/v1/audit 依赖 = 基线认证 + scope 模型生效时要求 "*" 通配。

    审计日志是最敏感数据面 (记录 actor/操作/目标, 可还原"谁在何时做了什么"),
    tokens[] scope 模型下窄 scope token (如 usage:read) 不得读全量审计 —— 对齐
    routes_logs Fix-46 的 "*" 口径。scope_dependency 为 None (未配 tokens[]) 时
    行为不变 (仅基线认证)。抽为模块级 helper 以控制 create_control_app 复杂度。
    """
    from fastapi import Depends

    deps: list[Any] = [Depends(auth_dependency)] if auth_dependency else []
    if scope_dependency:
        deps.append(Depends(scope_dependency("*")))
    return deps


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
    sparse_resolver: Any = None,
    workflow_engine: Any = None,
    identity_resolver: Any = None,
    vector_resolver: Any = None,
    channel_registry: Any = None,
    webhook_manager: Any = None,
    tenant_manager: Any = None,
    services: dict[str, Any] | None = None,
    audit_log: Any = None,
) -> Any:
    """创建 FastAPI 应用 (延迟导入 fastapi, 未安装时给出友好错误)。

    config 字段:
    - api_token: Bearer Token (为空时跳过认证, 仅开发模式)
    - tokens: Fix-12 Token Scope 模型 [{token, scopes}, ...] (未配置时回退 api_token)
    - agents_dir: AgentConfig 持久化目录 (默认 data/agents)
    - routing_rules_path: 路由规则文件 (默认 data/routing.jsonc)
    - links_path: 互联 Link 文件 (默认 data/links.jsonc)
    - audit_log_path: 审计日志 NDJSON 文件 (默认 data/audit.ndjson)
    - events_max_connections: Fix-14 SSE 同时在线连接数上限 (默认 100)
    - metrics_auth_enabled: CR3-L6 /metrics 是否要求 Bearer 认证 (默认 False,
      保持对 Prometheus 抓取开放; 控制面暴露到本机之外时建议开启)
    - session_auth_enabled: Fix-17 是否启用 /auth/session 会话 Cookie + CSRF
      机制 (默认 True; 未配置 api_token 也未配置 tokens[] 的纯开发模式下这个
      开关没有实际意义, 因为 make_auth_dependency 本身就会跳过认证)

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
        generate_session_secret,
        make_scope_dependency_factory,
        parse_token_scopes,
    )
    from isac.observability import get_default_metrics

    api_token = config.get("api_token", "")
    # Fix-12: control.tokens[] 未配置时 scope_dependency 为 None, 各路由端点的
    # scope 校验整体跳过, 行为与引入本模型之前完全一致 (只有扁平 api_token 认证)。
    parsed_tokens = parse_token_scopes(config)
    # R4: 控制面已启用但 api_token 与 tokens[] 均空时输出 CRITICAL 警告 (不阻止启动)。
    _warn_if_no_auth(api_token, parsed_tokens)
    # T3-backend: 首登强制设密码状态机 (对标 AstrBot password_change_required)。
    # setup_enabled 默认 False (向后兼容); config.sample.jsonc 的 control.setup_enabled=true
    # 让开箱首登强制设密码。启用后: 无 api_token/tokens 且 setup_state 无密码 → admin
    # 端点 428 SETUP_REQUIRED, 仅 /setup /health 可用。
    setup_manager = _build_setup_manager(config)
    # Fix-17: 认证根本没启用 (开发模式, 没配 api_token 也没配 tokens[]) 时会话
    # Cookie 机制没有意义 (没有 Token 可换); 否则默认启用, 可通过
    # session_auth_enabled=False 显式关闭 (如纯 API 网关场景不需要 WebUI)。
    session_secret: bytes | None = None
    if (api_token or parsed_tokens) and config.get("session_auth_enabled", True):
        session_secret = generate_session_secret()
    scope_dependency = (
        make_scope_dependency_factory(parsed_tokens, session_secret) if parsed_tokens else None
    )
    # tokens[] 配置生效时, 路由级基线认证必须按 tokens[] 校验 (而不是继续用扁平
    # api_token), 否则任何合法 scoped token 会在到达端点级 scope_dependency 检查
    # 之前就被拒绝 (401) —— 见 make_token_only_dependency 文档字符串。
    # 无 api_token/tokens 时 setup_manager 决定首登态 428 或纯开发模式 anonymous。
    auth_dependency = _build_auth_dependency(api_token, parsed_tokens, session_secret, setup_manager)
    # Fix-93: 允许接线方注入共享 AuditLog 实例 (与 MCP Server 同一实例, 审计统一);
    # 未注入时按 audit_log_path 自建 (向后兼容既有调用方/测试 fixture)。
    if audit_log is None:
        audit_log = AuditLog(log_path=config.get("audit_log_path", "data/audit.ndjson"))
    agents_dir = config.get("agents_dir", "data/agents")
    routing_rules_path = config.get("routing_rules_path", "data/routing.jsonc")
    links_path = config.get("links_path", "data/links.jsonc")
    metrics = metrics or get_default_metrics()

    # R15: 生产环境关闭 /docs Swagger UI 和 /openapi.json, 防止误暴露完整
    # admin 端点列表 + 参数形状。可通过 control.docs_enabled=true 显式开启
    # (开发/调试场景); 默认关闭 (安全默认)。
    docs_enabled = bool(config.get("docs_enabled", False))
    from isac import __version__

    app = FastAPI(
        title="ISAC Admin API",
        version=__version__,
        docs_url="/docs" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        redoc_url=None if not docs_enabled else "/redoc",
    )

    # R14: 全局 exception handler 兜底未捕获异常, 服务端 exc_info=True 记录
    # 完整堆栈, 客户端只返回通用 "internal error" 不泄露 Python 类型/字段
    # 路径/磁盘 IO 信息。HTTPException 由 FastAPI 默认处理 (保留 status code
    # 和 detail, 各路由已把 detail.message 改通用消息)。
    _register_global_exception_handler(app)
    # FE1: CORS 策略 (前后端分离)。origins 非空时加 CORSMiddleware 放开跨源;
    # 分离 origin 时 Session Cookie 降 SameSite=Lax (跨源可带), 同源保持 strict。
    cors_origins = _configure_cors(app, config)
    session_samesite = "lax" if cors_origins else "strict"
    # Fix-17: session_secret 非 None 时挂 CSRF middleware + /auth/session 路由
    # (CSRF 只对靠会话 Cookie 认证的写请求生效, 纯 Bearer Header 不受影响)。
    _mount_session_auth(app, api_token, parsed_tokens, session_secret, session_samesite)
    # T3-backend: 首登 setup 路由 (setup_manager 非 None 时挂载, 首登态也要可达)。
    _mount_setup_router(app, setup_manager)

    _mount_core_routers(
        app, agent_manager, router, bus, plugin_manager, config,
        auth_dependency, audit_log, agents_dir, routing_rules_path, links_path,
        scope_dependency,
    )
    # T6: 插件市场 + 安装 + 热重载路由。installer 在此构造 (plugins_dir/marketplace_url
    # 依赖 config); services 含共享注册表 + event_bus 等, 供 activation 激活 + sync。
    _mount_plugin_marketplace_router(
        app, agent_manager, plugin_manager, config, services or {},
        event_bus=event_bus, bus=bus, router=router,
        auth_dependency=auth_dependency, scope_dependency=scope_dependency,
        audit_log=audit_log,
    )
    _mount_optional_routers(
        app, usage_store, subagent_supervisor, provider_manager, model_catalog,
        artifact_store, session_manager, metadata_store, event_bus, auth_dependency,
        scope_dependency, parsed_tokens, config.get("events_max_connections"), audit_log,
        sparse_resolver, workflow_engine, identity_resolver, vector_resolver,
        webhook_manager, tenant_manager, session_secret,
        approval_gate=(services or {}).get("approval_gate"),
        session_event_store=(services or {}).get("session_event_store"),
    )

    # J3-2 配置编辑事务 + N1e 全局配置持久化/热重载路由。validate/diff 无外部依赖
    # 恒挂载; /config/global 系列仅在 services 注入了 global_config 时挂载
    # (生产 bootstrap 恒注入; 最小测试桩缺注入时行为退回 N1e 之前)。
    from isac.control.api import routes_config

    app.include_router(
        routes_config.build_router(
            auth_dependency=auth_dependency,
            agent_manager=agent_manager,
            global_config=(services or {}).get("global_config"),
            config_path=config.get("config_path", "data/config.jsonc"),
            override_path=config.get("config_override_path", "data/config.override.json"),
            audit_log=audit_log,
            scope_dependency=scope_dependency,
        ),
        prefix="/api/v1",
    )

    audit_deps = [Depends(auth_dependency)] if auth_dependency else []
    # Fix-107: /api/v1/audit 基线认证 + scope 模型生效时要求 "*" (见 _audit_read_deps)。
    audit_read_deps = _audit_read_deps(auth_dependency, scope_dependency)

    @app.get("/health")
    async def health() -> dict:
        """T4: 聚合各子系统状态, 让用户/运维一眼看到"哪儿有问题"。

        返回 {"status": "ok"|"degraded", "subsystems": {...}, "setup_required": bool};
        任一关键子系统异常 → status=degraded。setup_required=true 时控制面处于
        首登待设置态 (T3-backend), 仅 /setup 与 /health 可用。探针用途, 无认证。
        """
        result = _aggregate_health(agent_manager, provider_manager, config, channel_registry)
        result["setup_required"] = setup_manager is not None and setup_manager.is_setup_required
        return result

    @app.get("/api/v1/audit", dependencies=audit_read_deps)
    async def query_audit(
        action: str | None = None,
        actor: str | None = None,
        path_prefix: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return audit_log.query(action=action, actor=actor, path_prefix=path_prefix, limit=limit)

    # CR3-L6: /metrics 默认对 Prometheus 开放 (兼容既有部署, 且 enforce_safe_host
    # 已把控制面兜底在 127.0.0.1); 若部署上控制面暴露到内网/网关之后, 可配置
    # metrics_auth_enabled=true 让 /metrics 也走 Bearer 认证。
    metrics_deps = (
        [Depends(auth_dependency)]
        if (config.get("metrics_auth_enabled") and auth_dependency)
        else []
    )

    @app.get("/metrics", dependencies=metrics_deps)
    async def prometheus_metrics() -> Any:
        """Prometheus 文本格式 (默认不需认证; metrics_auth_enabled=true 时需要)。"""
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(metrics.to_prometheus(), media_type="text/plain")

    @app.get("/api/v1/metrics", dependencies=audit_deps)
    async def metrics_snapshot() -> dict:
        """JSON 指标快照 (供 WebUI 或监控系统集成, 需认证)。"""
        return metrics.snapshot()

    @app.get("/api/v1/config/schema", dependencies=audit_deps)
    async def config_json_schema() -> dict:
        """T3-backend: 暴露配置 JSON Schema (前端表单驱动前提, FE0/FE1 契约)。

        返回 ISACConfig.model_json_schema() (pydantic 生成的 JSON Schema), 前端据此
        渲染配置编辑表单 (字段类型/默认/校验), 不需手工编辑 config.jsonc。
        """
        from isac.utils.config_schema import ISACConfig

        return ISACConfig.model_json_schema()

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
    # Q5: 已加载插件列表端点 (供 WebUI 插件页读取真实数据, 替代占位假数据)。
    app.include_router(
        routes_plugins.build_loaded_plugins_router(
            plugin_manager,
            auth_dependency=auth_dependency,
            scope_dependency=scope_dependency,
        ),
        prefix="/api/v1",
    )


def _mount_plugin_marketplace_router(
    app: Any,
    agent_manager: Any,
    plugin_manager: PluginManager,
    config: dict[str, Any],
    services: dict[str, Any],
    *,
    event_bus: Any = None,
    bus: Any = None,
    router: Any = None,
    auth_dependency: Any = None,
    scope_dependency: Any = None,
    audit_log: Any = None,
) -> None:
    """T6: 挂载插件市场 + 安装 + 热重载 + 卸载 + 失败重试路由。

    installer 在此构造 (plugins_dir/marketplace_url 依赖 config)。services 含进程级
    共享注册表 (plugin_tools 等), 供 activation 模块激活 + sync 运行中 Agent。
    """
    from isac.control.api import routes_plugins
    from isac.plugin.runtime.installer import PluginInstaller

    plugins_cfg = (config.get("plugins", {}) or {}) if isinstance(config, dict) else {}
    plugins_dir = config.get("plugins_dir", "plugins")
    marketplace_url = plugins_cfg.get("marketplace_url", "")
    allow_install = bool(plugins_cfg.get("allow_install", True))

    installer = PluginInstaller(plugins_dir=plugins_dir, marketplace_url=marketplace_url)
    app.include_router(
        routes_plugins.build_plugin_marketplace_router(
            plugin_manager,
            agent_manager,
            installer,
            services,
            event_bus=event_bus,
            bus=bus,
            router=router,
            auth_dependency=auth_dependency,
            scope_dependency=scope_dependency,
            audit_log=audit_log,
            allow_install=allow_install,
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
    events_max_connections: int | None = None,
    audit_log: Any = None,
    sparse_resolver: Any = None,
    workflow_engine: Any = None,
    identity_resolver: Any = None,
    vector_resolver: Any = None,
    webhook_manager: Any = None,
    tenant_manager: Any = None,
    session_secret: bytes | None = None,
    approval_gate: Any = None,
    session_event_store: Any = None,
) -> None:
    """挂载可选路由 (usage/subagent/providers/config/sessions/memory/events/
    workflows/identity/webhooks/tenants/approvals)。"""
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
                audit_log=audit_log,
            ),
            prefix="/api/v1",
        )
    # J3-3: Sessions 路由 (session_manager 注入时挂载)
    if session_manager is not None:
        from isac.control.api import routes_sessions

        app.include_router(
            routes_sessions.build_router(
                session_manager, metadata_store,
                auth_dependency=auth_dependency, scope_dependency=scope_dependency,
            ),
            prefix="/api/v1",
        )
    # J3-3: Memory 路由 (metadata_store 注入时挂载; 无则返回 None 不挂载)
    from isac.control.api import routes_memory

    memory_router = routes_memory.build_router(
        metadata_store, auth_dependency=auth_dependency, scope_dependency=scope_dependency,
    )
    if memory_router is not None:
        app.include_router(memory_router, prefix="/api/v1")
    # N2: Memory 治理路由 (freeze/protect/correct/delete/restore/export);
    # 与 routes_memory 一致按 metadata_store 是否注入决定挂载, 无则不挂载。
    from isac.control.api import routes_memory_admin

    memory_admin_router = routes_memory_admin.build_router(
        metadata_store, auth_dependency=auth_dependency,
        scope_dependency=scope_dependency, audit_log=audit_log,
        sparse_resolver=sparse_resolver,
        vector_resolver=vector_resolver,
    )
    if memory_admin_router is not None:
        app.include_router(memory_admin_router, prefix="/api/v1")
    # J3-4: Events SSE 路由 (event_bus 注入时挂载)
    if event_bus is not None:
        from isac.control.api import routes_events

        kwargs: dict[str, Any] = {}
        if events_max_connections is not None:
            kwargs["max_connections"] = events_max_connections
        app.include_router(
            routes_events.build_router(
                event_bus, auth_dependency=auth_dependency, tokens=tokens,
                session_secret=session_secret, **kwargs,
            ),
            prefix="/api/v1",
        )
    # S4/S5 (P4/P5): identity 与 workflow 控制面路由 (注入时挂载; 无则返回 None 不挂载)。
    _mount_identity_workflow_routers(
        app, identity_resolver, workflow_engine,
        auth_dependency=auth_dependency, scope_dependency=scope_dependency, audit_log=audit_log,
    )
    # T4: 实时日志 SSE 端点 (LogBuffer 单例启用时挂载; 否则返回 None 不挂载)。
    from isac.control.api import routes_logs

    logs_router = routes_logs.build_router(
        auth_dependency=auth_dependency, scope_dependency=scope_dependency,
    )
    if logs_router is not None:
        app.include_router(logs_router, prefix="/api/v1")
    # R2-③: Webhook 路由 (抽到 helper 降 _mount_optional_routers 复杂度)
    _mount_webhook_router(
        app, webhook_manager, auth_dependency=auth_dependency,
        scope_dependency=scope_dependency, audit_log=audit_log,
    )
    # R6-①: 租户路由 (tenant_manager 注入时挂载; #25 透传 tokens/session_secret 做绑定强制)
    _mount_tenant_router(
        app, tenant_manager, auth_dependency=auth_dependency,
        scope_dependency=scope_dependency, audit_log=audit_log,
        tokens=tokens, session_secret=session_secret,
    )
    # U5: 审批路由 (approval_gate 注入时挂载; HITL ask 档运维侧回流)
    _mount_approvals_router(
        app, approval_gate, auth_dependency=auth_dependency,
        scope_dependency=scope_dependency, audit_log=audit_log,
        session_event_store=session_event_store,
    )


def _mount_approvals_router(
    app: Any, approval_gate: Any, *,
    auth_dependency: Any, scope_dependency: Any, audit_log: Any,
    session_event_store: Any = None,
) -> None:
    """U5: 挂载审批控制面路由 (approval_gate 注入时; 无则返回 None 不挂载)。"""
    if approval_gate is None:
        return
    from isac.control.api import routes_approvals

    router = routes_approvals.build_router(
        approval_gate, auth_dependency=auth_dependency,
        scope_dependency=scope_dependency, audit_log=audit_log,
        session_event_store=session_event_store,
    )
    if router is not None:
        app.include_router(router, prefix="/api/v1")


def _mount_tenant_router(
    app: Any, tenant_manager: Any, *,
    auth_dependency: Any, scope_dependency: Any, audit_log: Any,
    tokens: Any = None, session_secret: bytes | None = None,
) -> None:
    """R6-①: 挂载租户控制面路由 (tenant_manager 注入时; 仿 routes_workflows 无注入返回 None)。

    #25: tokens/session_secret 透传给路由做租户绑定强制 (绑定租户的 token 只能
    操作自己的租户); 未配置 tokens[] 时行为与之前完全一致。
    """
    if tenant_manager is None:
        return
    from isac.control.api import routes_tenants

    router = routes_tenants.build_router(
        tenant_manager, auth_dependency=auth_dependency,
        scope_dependency=scope_dependency, audit_log=audit_log,
        tokens=tokens, session_secret=session_secret,
    )
    if router is not None:
        app.include_router(router, prefix="/api/v1")


def _mount_webhook_router(
    app: Any, webhook_manager: Any, *,
    auth_dependency: Any, scope_dependency: Any, audit_log: Any,
) -> None:
    """R2-③: 挂载 Webhook 订阅与触发路由 (webhook_manager 注入时)。"""
    if webhook_manager is None:
        return
    from isac.control.api import routes_webhooks

    app.include_router(
        routes_webhooks.build_router(
            webhook_manager, auth_dependency=auth_dependency,
            scope_dependency=scope_dependency, audit_log=audit_log,
        ),
        prefix="/api/v1",
    )


def _mount_identity_workflow_routers(
    app: Any,
    identity_resolver: Any,
    workflow_engine: Any,
    *,
    auth_dependency: Any,
    scope_dependency: Any,
    audit_log: Any,
) -> None:
    """挂载 identity (S4) 与 workflow (S5) 控制面路由 (helper 抽出避免 C901)。"""
    from isac.control.api import routes_identity, routes_workflows

    workflow_router = routes_workflows.build_router(
        workflow_engine, auth_dependency=auth_dependency,
        scope_dependency=scope_dependency, audit_log=audit_log,
    )
    if workflow_router is not None:
        app.include_router(workflow_router, prefix="/api/v1")
    identity_router = routes_identity.build_router(
        identity_resolver, auth_dependency=auth_dependency,
        scope_dependency=scope_dependency, audit_log=audit_log,
    )
    if identity_router is not None:
        app.include_router(identity_router, prefix="/api/v1")
