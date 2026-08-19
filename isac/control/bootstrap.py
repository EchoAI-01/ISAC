"""U2 控制面装配: control-plane API 路由注册 + webhook 事件订阅。

原 isac/main.py 的 _register_control_plane/_setup_webhooks 拆出 (U2 装配层重构)。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from isac.core.events import EventType
from isac.dispatch import _noop_start
from isac.gateway.event_bus import EventBus
from isac.observability import MetricsCollector
from isac.router.router import MessageRouter
from isac.runtime.application import ApplicationRuntime
from isac.runtime.bus import InterAgentBus
from isac.runtime.manager import AgentManager
from isac.runtime.plugin_bootstrap import (
    _build_plugin_enable_matrix,
    _build_workflow_engine,
    _fire_plugin_on_load,
    _register_mcp_server,
)
from isac.utils.logger import get_logger

DATA_DIR = Path("data")

logger = get_logger(__name__)

async def _register_control_plane(
    runtime: ApplicationRuntime,
    control_config: dict[str, Any],
    agent_manager: AgentManager,
    router: MessageRouter,
    bus: InterAgentBus,
    metrics: MetricsCollector,
    usage_store: Any = None,
    subagent_supervisor: Any = None,
    provider_manager: Any = None,
    model_catalog: Any = None,
    artifact_store: Any = None,
    session_manager: Any = None,
    metadata_store: Any = None,
    event_bus: Any = None,
    webhook_manager: Any = None,
    *,
    services: dict[str, Any] | None = None,
    channel_registry: Any = None,
) -> None:
    """把控制面 (uvicorn Server) 注册到 runtime 的生命周期管理。

    uvicorn Server 用 should_exit=True 触发优雅关闭, 再 await shutdown() 等连接退出;
    serve() 是长循环, 通过 runtime.spawn 挂到 TaskGroup 持有强引用
    (CODE_REVIEW_REPORT.md #12/#13)。
    """
    try:
        import uvicorn

        from isac.control.api.server import create_control_app
        from isac.control.defaults import enforce_safe_host
        from isac.plugin.runtime.manager import PluginManager

        # 用真实配置初始化 PluginManager, 并加载 plugins/ 目录下的全部插件。
        # 失败不阻塞控制面启动: 加载报告会作为日志输出, 单个插件加载错误由 PluginManager
        # 自身错误隔离 (CODE_REVIEW_REPORT.md #27)。
        plugin_config = (control_config.get("plugins", {}) or {}) if isinstance(control_config, dict) else {}
        # Q3 激活: PluginManager 接入 EnableMatrix —— 此前 is_enabled_for 默认放行
        # (enable_matrix=None → True), 部署方无法按 Agent/Channel/全局矩阵控制插件
        # 启用。从 global_config 构造全局 EnableMatrix 注入, 让插件加载后也能参与
        # 矩阵决策 (call_on_load 阶段先全部加载; 真实启用判定在 per-Agent 调用
        # is_enabled_for 时按 Agent 配置 + Channel + 全局三路取交集)。
        plugin_manager = PluginManager(
            plugin_config, enable_matrix=_build_plugin_enable_matrix(services)
        )
        # H2: 隔离插件跑在子进程 (daemon), 优雅关闭时显式终止, 不留残余子进程。
        runtime.register_lifecycle("plugins", _noop_start, plugin_manager.shutdown)
        plugins_dir = Path(control_config.get("plugins_dir", "plugins"))
        # T6: 无条件记录 plugins_dir 供 reload/install/retry 定位 (即使目录尚不存在,
        # 后续经控制面 install 会创建; 否则 reload 报 "plugins_dir 未设置")。
        plugin_manager._plugins_dir = plugins_dir  # noqa: SLF001
        # 用 to_thread 包装 Path.exists 避免 event loop 内 blocking IO (ruff ASYNC240)。
        if await asyncio.to_thread(plugins_dir.exists):
            try:
                load_report = await plugin_manager.load_all(plugins_dir)
                if load_report:
                    logger.info("插件加载完成", report=load_report)
                # CR3-H2/R3: 接线 on_load 生命周期钩子 + 插件注册表/兼容层桥接。
                # 此前 call_on_load 全仓无调用点, 插件即使被加载也是"惰性"的
                # (无法注册事件订阅/互联钩子/Admin Route)。event_bus/inter_agent_bus/
                # router 都是生产实例, 插件经 on_event_intercept/on_event_async 的
                # 订阅会真实参与 process_message 主链路。R3 起 tools/commands/
                # prompt_builder 改为进程级共享注册表 (`plugin_tools` 等服务键),
                # native 插件 on_load register 真实写入, 兼容层 (AstrBot/MaiBot) 经
                # _adapt_compat_plugins 桥接 @filter.llm_tool/@register_action;
                # assemble_agent 合并进 per-Agent registry。详见 _fire_plugin_on_load docstring。
                await _fire_plugin_on_load(
                    plugin_manager, services or {}, event_bus=event_bus, bus=bus, router=router
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("插件加载过程异常, 不阻塞控制面", error=str(exc), exc_info=True)

        # CR3-L3: BM25 内存索引解析器 (namespace → SparseBM25Index), 让治理路由的
        # delete/restore/correct 能同步内存索引。
        sparse_indexes = (services or {}).get("sparse_indexes") or {}
        # S5 (O3): 工作流引擎 (默认关闭: control.workflow.enabled!=true → None → 路由
        # 不挂载, 零行为变化)。启用时构造并注入, WorkflowEngine 按 base_dir 持久化实例。
        # S5 激活: 同时注入生产 action_handler + condition_evaluator + 声明式加载。
        workflow_engine = _build_workflow_engine(control_config, agent_manager)
        # Fix-93: 构造**共享** AuditLog 实例 —— 同时注入 HTTP 控制面与 MCP Server,
        # 使两条写通道审计进同一内存缓冲/NDJSON 文件 (此前 MCP 完全绕过审计)。
        from isac.control.audit import AuditLog

        shared_audit_log = AuditLog(
            log_path=control_config.get("audit_log_path", "data/audit.ndjson")
        )
        app = create_control_app(
            agent_manager,
            router,
            bus,
            plugin_manager,
            control_config,
            metrics=metrics,
            usage_store=usage_store,
            subagent_supervisor=subagent_supervisor,
            provider_manager=provider_manager,
            model_catalog=model_catalog,
            artifact_store=artifact_store,
            session_manager=session_manager,
            metadata_store=metadata_store,
            event_bus=event_bus,
            sparse_resolver=sparse_indexes.get,
            workflow_engine=workflow_engine,
            identity_resolver=(services or {}).get("identity_resolver"),
            vector_resolver=(services or {}).get("vector_resolver"),
            channel_registry=channel_registry,
            webhook_manager=webhook_manager,
            tenant_manager=(services or {}).get("tenant_manager"),
            services=services or {},
            audit_log=shared_audit_log,
        )
        host = enforce_safe_host(control_config.get("host", "127.0.0.1"))
        port = int(control_config.get("port", 8765))
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
        )
        server = uvicorn.Server(config)

        async def _start_control() -> None:
            # uvicorn.Server.serve 是阻塞循环, 通过 runtime.spawn 挂到 TaskGroup;
            # serve_forever 的 request_stop 设置 server.should_exit 让 serve 返回。
            runtime.spawn(server.serve(), name="control-plane-uvicorn")

        async def _stop_control() -> None:
            server.should_exit = True
            try:
                await asyncio.wait_for(server.shutdown(), timeout=5.0)
            except TimeoutError:
                logger.warning("控制面 5 秒未完成优雅关闭, 继续往下走")
            except Exception as exc:  # noqa: BLE001
                logger.warning("控制面关闭异常", error=str(exc))

        runtime.register_lifecycle("control_plane", _start_control, _stop_control)
        logger.info("控制面已注册", host=host, port=port)
        # R2-④: MCP Server stdio 启动点 (抽到 helper 降 _register_control_plane 复杂度)
        # Fix-93: 注入共享 AuditLog, MCP 写工具与 HTTP 控制面统一审计。
        _register_mcp_server(
            runtime, control_config, services, agent_manager, router, bus, plugin_manager,
            audit_log=shared_audit_log,
        )
    except Exception as exc:
        logger.error("控制面注册失败 (不阻塞数据面)", error=str(exc), exc_info=True)


def _setup_webhooks(event_bus: EventBus) -> Any:
    """R2-③: 构造 WebhookManager + EventBus on_async 订阅 (消息事件 → webhook 推送)。

    WebhookManager 类此前已实现但 main 不构造 + 不订阅 EventBus → 死代码。
    on_async 异常隔离, webhook 推送失败不阻塞主流程。
    """
    from isac.control.webhooks import WebhookManager

    webhook_manager = WebhookManager()
    # Fix-55: 后台推送任务强引用集合 (asyncio 只弱引用 task, 不持引用会被 GC)。
    _webhook_bg_tasks: set[asyncio.Task[None]] = set()

    async def _dispatch_webhook(payload: Any, event_name: str = "") -> None:
        # Fix-55: 此前直接 await dispatch —— 死/慢订阅 URL 的重试退避 (3 次 × 10s
        # 超时 + 1s/2s 退避 ≈ 32s) 会经 fire_async 把**会话锁内**的 process_message
        # 整段卡住, 一个死订阅 = 该会话每条消息阻塞半分钟。改后台任务推送:
        # 本协程立即返回, 锁即刻释放; 推送成败都在任务内处理。
        async def _push() -> None:
            try:
                await webhook_manager.dispatch(event_name, {"event": event_name, "payload": payload})
            except Exception as exc:  # noqa: BLE001
                logger.warning("Webhook 推送失败 (后台)", event=event_name, error=str(exc))

        task = asyncio.create_task(_push())
        _webhook_bg_tasks.add(task)
        task.add_done_callback(_webhook_bg_tasks.discard)

    # Fix-80: 事件名用 CONTROL_PLANE_SPEC.md §5.1 目录名 (message.*), 不再直发
    # EventBus 枚举值 —— 此前发 "post_message"/"post_send", 按文档订阅
    # message.responded 的接收方永远收不到推送 (WebhookManager.canonical_event
    # 同时兼容旧名订阅)。
    event_bus.on_async(EventType.POST_MESSAGE, lambda p: _dispatch_webhook(p, "message.responded"))
    event_bus.on_async(EventType.POST_SEND, lambda p: _dispatch_webhook(p, "message.sent"))
    return webhook_manager
