"""U2 应用启动编排 (bootstrap): main() 运行时生命周期 (服务装配 → Agent 恢复 →
通道/路由 → 控制面 → 插件 → 生命周期注册 → 优雅关停)。

原 isac/main.py 启动编排拆出 (U2 装配层重构); 控制面注册见 isac/control/bootstrap.py,
插件集成见 isac/runtime/plugin_bootstrap.py, 通道注册见 isac/channel/registration.py。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from isac.channel.model import ISACMessage
from isac.channel.registration import _ensure_default_routing, _register_channel_adapters
from isac.channel.registry import ChannelRegistry
from isac.control.bootstrap import _register_control_plane, _setup_webhooks
from isac.core.constants import INTERAGENT_PLATFORM
from isac.core.events import EventType
from isac.dispatch import (
    _build_identity_resolver,
    _noop_start,
    _shutdown_message_pipeline,
    make_message_dispatcher,
)
from isac.gateway.event_bus import EventBus
from isac.gateway.lock import SessionLockManager
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.observability import AlertManager, MetricsCollector, get_default_alert_rules
from isac.router.router import MessageRouter
from isac.router.rules import load_rules
from isac.runtime.application import ApplicationRuntime
from isac.runtime.bus import InterAgentBus, InterAgentLink, InterAgentMessage
from isac.runtime.manager import AgentManager, ensure_default_agent, load_persisted_agents
from isac.runtime.mesh.query import _answer_memory_query
from isac.utils.config import load_config
from isac.utils.logger import get_logger, setup_logger
from isac.utils.security import resolve_secrets_in_config
from isac.wiring import (
    _build_secret_store,
    _build_session_history_kernel,
    _build_tool_permission_pipeline,
    _wire_llm_capabilities,
    build_services,
    register_llm_provider,
)

logger = get_logger(__name__)

DATA_DIR = Path("data")

# T2: 首启自动创建的 data/ 子目录 (被 build_services 各组件引用的路径)。
# 集中创建 + 各组件既有惰性 mkdir 双保险; 这里只建目录占位, 不创建文件, 零行为变化。
_DATA_SUBDIRS: tuple[str, ...] = (
    "agents",
    "memory",
    "gateway",
    "artifacts",
    "subagent",
    "usage",
    "workflows",
)

def _ensure_data_dirs() -> None:
    """T2: 首启自动创建 data/ 及被引用子目录。

    此前各组件惰性自建 (path.parent.mkdir), 无统一入口; 集中创建让首启目录结构透明、
    日志可观测。已存在目录 exist_ok=True 零冲突; 不创建文件, 不触碰既有数据。
    """
    for sub in _DATA_SUBDIRS:
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)


async def _start_session_event_store(store: Any, deny_guard: Any = None) -> None:
    """U1: 会话事件存储启动 —— 建表 + 逐分区 torn-tail 修复 (抽自 main 降 C901)。

    U5/Fix-120: deny_guard 注入时经 ``restore_from_store`` 从事件流**全量**重建单调
    拒绝账本 (分页扫全量, 不受"最近 N 条"窗口截断) —— 拒绝跨进程重启仍不可翻回。
    """
    await store.start()
    for key in await store.list_session_keys():
        await store.repair_torn_tail(key)
    if deny_guard is not None:
        await deny_guard.restore_from_store(store)


async def _close_storage_stores(services: dict[str, Any]) -> None:
    """C1: shutdown 时关闭 VectorStore/GraphStore 持久连接, 防 WAL/SHM 残留 + FD 泄漏。

    此前 storage lifecycle 的 stop 是 _noop_start, 持久连接在进程退出前不显式 close,
    嵌入启用时长期运行会让 vectors-<ns>.db 的 WAL/SHM 文件残留 + aiosqlite FD 泄漏。
    """
    vs_dict = services.get("vector_stores") or {}
    for ns, store in vs_dict.items():
        close = getattr(store, "close", None)
        if callable(close):
            try:
                await close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("VectorStore close 失败, 已忽略", namespace=ns, error=str(exc))
    gs = services.get("graph_store")
    if gs is not None:
        close = getattr(gs, "close", None)
        if callable(close):
            try:
                await close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("GraphStore close 失败, 已忽略", error=str(exc))


async def main() -> None:
    """应用主入口。

    使用 ApplicationRuntime 统一管理后台任务生命周期 (K1, DEVELOPMENT_PLAN.md):
    - Channel/Control/Alert 等资源 register_lifecycle 成对注册, 启动按注册顺序、
      关闭按 LIFO 倒序
    - 后台 task 通过 runtime.spawn 挂到统一 TaskGroup, 持有强引用不被 GC
    - SIGINT/SIGTERM 触发 request_stop(), 进入优雅关闭
    - 之前 main 调 channel_registry.start_all() 后直接返回, 后台 task 随事件循环
      结束被取消的 bug 已修 (CODE_REVIEW_REPORT.md #12/#13)
    """
    # N1e: override_path 载入控制面写入的全局配置覆盖层 (加载序: 默认 ← config.jsonc ← override ← 环境变量)。
    global_config = load_config(DATA_DIR / "config.jsonc", override_path=DATA_DIR / "config.override.json")
    # T2: 首启自动创建 data/ 及被引用子目录。此前各组件惰性自建 (path.parent.mkdir),
    # 但无统一入口, 首启日志零反馈、目录结构不透明。集中创建双保险 (各组件既有惰性
    # mkdir 保留, 零冲突)。
    _ensure_data_dirs()
    # R5: 密钥安全。配置中 api_key 形如 "secret:<key>" 时经 SecretStore 解密 (AES-256-GCM,
    # env ISAC_SECRET_KEY 加载)。env 未配置时不构造 store → secret: 前缀值原样回退
    # (warning), 走原明文路径, 向后兼容。在 build_services/register_llm_provider 之前
    # 就地解析, 使同步注册函数拿到明文 api_key。env ISAC_LLM_API_KEY 仍最高优先级
    # (load_config 已写入 llm.api_key, 非 secret: 前缀原样返回)。
    secret_store = _build_secret_store()
    await resolve_secrets_in_config(global_config, secret_store)
    # T4: 启用 LogBuffer 单例, 必须在 setup_logger 之前 (cache_logger_on_first_use 后
    # 装不进 processor 链)。setup_logger 检测单例存在才插入 buffer processor。
    from isac.utils.log_buffer import enable_log_buffer

    enable_log_buffer()
    _logging_cfg = global_config.get("logging", {}) or {}
    # debug=true 视为全局 DEBUG; 否则用 log_level / logging.level; 均缺省时 setup_logger 落 INFO。
    _level = "debug" if global_config.get("debug") else (global_config.get("log_level") or _logging_cfg.get("level"))
    setup_logger(
        debug=bool(global_config.get("debug", False)),
        log_format=_logging_cfg.get("format", "console"),
        level=_level,
        per_module=_logging_cfg.get("per_module"),
    )
    logger.info("ISAC 启动中", version=_get_version())

    runtime = ApplicationRuntime()
    runtime.install_signal_handlers()

    # ── Provider ────────────────────────────────────────────
    services = build_services(global_config)
    metrics: MetricsCollector = services.metrics
    register_llm_provider(services.provider_manager, global_config.get("llm", {}))
    # U7: 能力快照接线 (model_router 注入 + primary LLM 描述符注册, 见函数 docstring)
    _wire_llm_capabilities(services, global_config)

    # ── Runtime (Agent 管理 + 互联总线) ─────────────────────
    agent_manager = AgentManager(services)
    from isac.runtime.subagent.runner import configure_subagent_runner

    configure_subagent_runner(services["subagent_supervisor"], agent_manager)
    bus = InterAgentBus()
    # 互联投递专用 SessionManager: P2 起进程内共享一个实例 (此前每次投递新建,
    # 跨 Agent 会话永不复用, 目标 Agent 每条互联消息都像陌生会话)。
    interagent_session_mgr = SessionManager(global_config)

    # 投递回调: 把 InterAgentMessage 路由到目标 Agent 的 handle_message。
    # 命令 (ask_agent) 现在能拿到 response 而不是恒 None (CODE_REVIEW_REPORT.md #3)。
    async def _deliver_to_agent(target_agent_id: str, message: InterAgentMessage) -> str | None:
        # P2: MEMORY_QUERY 不进 LLM 聊天 —— 按 visible_memory_scopes 裁剪后直接跑
        # 目标 Agent 的记忆检索, 结果经 bus response 同步返回查询方。
        if message.type == "memory_query":
            return await _answer_memory_query(agent_manager, target_agent_id, message)
        # 互联消息复用原消息的 session 上下文; 跨 Agent 时把 from_agent 当作 user_id
        # 让目标 Agent 不会因 has_at=False 而被门控过滤。但目标 Agent 的 handle_message
        # 依赖真实 Session/UserProfile; 这里构造一个最小可路由会话。
        content = message.content
        if message.type == "handoff":
            # P2: 接手方明确知道这是会话交接 (摘要), 而非用户发来的普通消息
            summary = str(message.context.get("summary", "") or message.content)
            content = f"[会话交接] 来自 {message.from_agent} 的交接摘要: {summary}"
        wrapped = ISACMessage(
            msg_id="",
            platform=INTERAGENT_PLATFORM,
            timestamp=0,
            user_id=message.from_agent,
            user_name="",
            group_id=None,
            content=content,
        )
        session = await interagent_session_mgr.get_or_create(wrapped, agent_id=target_agent_id)
        # R2-1: 经会话锁串行化 —— 此前直调 handle_message 绕过 _process_locked 的
        # session_lock, P0 并行下两次并发投递会重叠跑同一互联会话。
        return await agent_manager.handle_message_serialized(target_agent_id, wrapped, session, None)

    bus.set_deliver(_deliver_to_agent)
    # 启动时从 data/links.jsonc 恢复已持久化的互联 Link (CODE_REVIEW_REPORT.md #3)。
    await _load_persisted_links(bus, DATA_DIR / "links.jsonc")
    # Link 持久化回调: add_link/remove_link 改动时落盘 (失败只记日志, 不回滚 in-memory)。
    def _persist_links_snapshot() -> None:
        from isac.control.api.routes_routing import _persist_links

        _persist_links(bus, DATA_DIR / "links.jsonc")

    bus.set_persist(_persist_links_snapshot)
    # 把 bus 也加入 services, 让 ask_agent 工具与命令能通过 context.services 访问。
    services["bus"] = bus

    # ── Router (Channel 与 Agent 解耦) ──────────────────────
    rules = load_rules(global_config.get("router", {}).get("rules_file", DATA_DIR / "routing.jsonc"))
    router = MessageRouter(rules, agents_provider=agent_manager.routing_infos)
    # P2: handoff_conversation 工具经 services["router"] 登记会话归属转移
    services["router"] = router

    # ── Channel ─────────────────────────────────────────────
    channel_registry = ChannelRegistry()
    _register_channel_adapters(channel_registry, global_config)

    # ── Gateway ─────────────────────────────────────────────
    event_bus = EventBus()
    session_mgr = SessionManager(global_config, db_path=str(DATA_DIR / "gateway" / "sessions.db"))
    # Q1: 跨平台身份映射 SQLite 持久化 (master_id/person_id 跨重启稳定,
    # 人物画像与记忆按归一身份聚合的前提)
    user_mapper = UserMapper(str(DATA_DIR / "gateway" / "identity.db"))
    # S4: 跨平台身份归一器 (默认关闭 → None → 主链路走 user_mapper 原路径, 零行为变化)。
    identity_resolver = _build_identity_resolver(global_config, user_mapper)
    # S4 控制面入口 (bind/conflicts): 放进 services 让 _register_control_plane 透传给
    # create_control_app。仅在 identity.enabled=true 时非空, 默认关闭不挂载路由。
    services["identity_resolver"] = identity_resolver
    session_lock = SessionLockManager()
    # P1: 注入 gateway/channel 句柄到共享 services —— 主动任务强制话轮需要按
    # session_id 反查会话 (session_mgr)、经会话锁串行 (session_lock)、把回复
    # 发回原 Channel (channel_registry); /mute 等命令路径也读 session_mgr。
    services["session_mgr"] = session_mgr
    services["session_lock"] = session_lock
    # U8 SessionWriteGate: 会话写入统一仲裁门 (先预约后写入, hold 窗口, fail-closed)。
    # 强制话轮/handoff 等主动写入路径经此门串行; 未接门 (如测试夹具) 时旧行为保持。
    from isac.runtime.write_gate import SessionWriteGate

    services["session_write_gate"] = SessionWriteGate()
    services["channel_registry"] = channel_registry

    # U1: 事件溯源会话内核 —— append-only 会话事件表 + 滑动窗口历史派生器。
    # store 注册生命周期 (启动建表 + torn-tail 修复, 关闭 flush); deriver 按配置构造。
    # manager._derive_session_history 据此在每回合派生历史窗口 (开箱可用)。
    session_event_store, session_history_deriver = _build_session_history_kernel(global_config)
    services["session_event_store"] = session_event_store
    services["session_history"] = session_history_deriver

    # U5: 工具权限管线 —— ApprovalGate (ask 档人工审批, 超时 fail-closed) +
    # DenyGuard (单调拒绝账本, 拒绝不可翻回, 启动时从事件流重建)。注入 services
    # 供 ToolRegistry.execute 四段管线与 process_message 审批回复拦截使用。
    approval_gate, deny_guard = _build_tool_permission_pipeline(global_config)
    services["approval_gate"] = approval_gate
    services["deny_guard"] = deny_guard

    # P0: 消息处理并发化 —— handle_message 只负责派生任务立即返回, 适配器收取
    # 循环不再被单条消息的 LLM 往返阻塞 (跨会话真并行); 单会话仍靠会话锁串行。
    handle_message, drain_inflight = make_message_dispatcher(
        event_bus=event_bus,
        router=router,
        session_mgr=session_mgr,
        user_mapper=user_mapper,
        agent_manager=agent_manager,
        channel_registry=channel_registry,
        metrics=metrics,
        session_lock=session_lock,
        identity_resolver=identity_resolver,
    )

    # 注入 Channel 适配器的消息回调
    for adapter in channel_registry.list():
        adapter.on_message = handle_message

    # ── Alert (规则驱动; 在 start 之前注册, 启动后才挂到 TaskGroup) ──
    # R2-③: WebhookManager 此前已实现但 main 不构造 + AlertManager 不注入 → 死代码。
    # 本轮构造 WebhookManager + EventBus on_async 订阅 + 注入 AlertManager (抽到 helper
    # 降 main 复杂度)。
    webhook_manager = _setup_webhooks(event_bus)
    alert_manager = AlertManager(metrics, webhook_manager=webhook_manager)
    for rule in get_default_alert_rules():
        alert_manager.add_rule(rule)

    # ── 启动编排 (K1): 所有资源通过 register_lifecycle 注册到 runtime ──
    # P0: channels 改到最后注册 (见 runtime.start() 前) —— LIFO 关闭时最先停止
    # 消息入口并 drain 在途任务, 之后才关 journal/usage/providers 等下游资源;
    # 此前 channels 最先注册 → 最后关闭, providers 连接池会在在途消息还没
    # 处理完时先被关掉。启动侧 channels 最后 start 也更合理 (一切就绪才开闸)。
    control_config = global_config.get("control", {}) or {}
    if control_config.get("enabled"):
        # CR3: session_mgr/event_bus 此前经 services.get() 取值恒 None (键根本
        # 不存在), routes_sessions/routes_events 在生产从未挂载; 现在把 main()
        # 内已构造的真实实例直接传入。
        await _register_control_plane(
            runtime, control_config, agent_manager, router, bus, metrics,
            services.get("usage_store"), services.get("subagent_supervisor"),
            services.provider_manager, services.model_catalog,
            services.artifact_store,
            session_mgr, services.get("metadata_store"),
            event_bus,
            webhook_manager,
            services=services,
            channel_registry=channel_registry,
        )
    runtime.register_lifecycle(
        "alerts",
        alert_manager.start,
        alert_manager.stop,
    )
    # K2: Provider (httpx.AsyncClient 连接池) 在 shutdown 时 aclose, 避免连接泄漏;
    # 启动无需动作 (httpx.AsyncClient 惰性创建, 首次 chat 时才建池)。
    provider_manager = services.provider_manager
    runtime.register_lifecycle(
        "providers",
        _noop_start,
        provider_manager.aclose,
    )

    # K3: 先执行 storage schema init/migration (MetadataStore + VectorStore), 保证
    # 后续 load_persisted_agents 创建 Agent 时 warm_up_sparse_index 能从 SQLite 读数据;
    # 再注册到 runtime 的 LIFO 关闭链 (storage 关闭时无显式动作, aiosqlite 每次连接即关)。
    storage_start = services["storage_start"]
    await storage_start()

    # C1: shutdown 时关闭 VectorStore/GraphStore 持久连接, 防 WAL/SHM 残留 + FD 泄漏。
    # 此前 storage lifecycle 的 stop 是 _noop_start, 持久连接在进程退出前不显式 close,
    # 嵌入启用时长期运行会让 vectors-<ns>.db 的 WAL/SHM 文件残留 + aiosqlite FD 泄漏。
    runtime.register_lifecycle("storage", _noop_start, lambda: _close_storage_stores(services))

    # J2: 制品存储生命周期 (启动 schema 初始化 + 周期 TTL 扫描; 关闭时 sweep 兜底)。
    # ArtifactStore 在 build_services 中无条件构造, 这里无条件注册: 即使无多模态
    # Provider 注册, start_ttl_sweep 也只是周期扫描空 DB, 开销可忽略。
    artifact_store = services.artifact_store
    runtime.register_lifecycle("artifact_store", artifact_store.start, artifact_store.stop)

    # N5b 批次G: 入站媒体 uploads_store 同样需注册生命周期 (start_ttl_sweep 周期清理
    # 7 天过期的下载媒体)。此前只注册了 artifact_store, uploads_store.start 从未被调用
    # → sweep 任务不跑, 入站媒体文件 + DB 行无限堆积 (incoming_media.py 每次 put 写
    # 7 天过期元数据但无人扫)。uploads_store 在 build_services 无条件构造并放入 services
    # (同 artifact_store), 此处无条件注册。
    uploads_store = services.uploads_store
    runtime.register_lifecycle("uploads_store", uploads_store.start, uploads_store.stop)

    # U1: 会话事件存储生命周期 (启动建表 + 逐分区 torn-tail 修复; 关闭 flush)。
    # torn-tail: kill -9 可能留下孤儿 tool.called (无 outcome), 重放前合成 OUTCOME_UNKNOWN。
    # U5: 同步从事件流重建 DenyGuard 拒绝账本 (拒绝跨重启不可翻回)。
    runtime.register_lifecycle(
        "session_events",
        lambda: _start_session_event_store(session_event_store, deny_guard),
        session_event_store.stop,
    )

    # J1: 用量存储生命周期 (仅启用计量时注册; stop 时先 flush 缓冲再关连接)。
    _register_usage_lifecycle(runtime, services)
    # J4: 子任务日志生命周期 (仅启用 subagent.enabled 时注册)。
    _register_subagent_lifecycle(runtime, services)

    # P0: channels 最后注册 —— 启动侧一切资源就绪后才开消息闸; 关闭侧 (LIFO
    # 最先执行) 先停适配器收取, 再 drain 在途消息任务, 保证 journal/usage/
    # providers 等下游资源关闭时不再有消息在途 (不丢消息)。
    async def _stop_channels_and_drain() -> None:
        await _shutdown_message_pipeline(channel_registry, drain_inflight, agent_manager)

    runtime.register_lifecycle(
        "channels",
        channel_registry.start_all,
        _stop_channels_and_drain,
    )

    # 先恢复持久化 Agent (data/agents/*/config.jsonc, enabled=true 的自动 start),
    # 再回退到默认 Agent 保证无任何持久化配置时也能跑通 (CODE_REVIEW_REPORT.md #2)。
    agents_dir = global_config.get("control", {}).get(
        "agents_dir", str(DATA_DIR / "agents")
    )
    restore_report = await load_persisted_agents(agent_manager, agents_dir)
    if restore_report:
        logger.info("持久化 Agent 恢复完成", report=restore_report)
    default_instance = await ensure_default_agent(agent_manager, global_config)
    # Q0: 裸部署无任何路由规则时, 已启用平台的消息兜底路由到默认 Agent (否则全 DROP)
    _ensure_default_routing(router, channel_registry, default_instance.agent_id)
    await event_bus.fire_async(EventType.ON_START, {"config": global_config})

    # ── 进入 runtime (启动 TaskGroup + 触发所有 register_lifecycle.start) ──
    await runtime.start()
    # J4-3: SubAgent 重启恢复 — 把 running/queued 标记为 cancelled (中断后不恢复旧进度)。
    # 必须在 runtime.start() 之后调用 (subagent_journal 已 start, DB 连接就绪)。
    await _restore_subagent_interrupts(services)
    logger.info("ISAC 启动完成")
    # Q0: try/finally 保证优雅关闭 —— Windows 上 add_signal_handler 注册失败,
    # Ctrl+C 以 KeyboardInterrupt/CancelledError 穿透 serve_forever, 此前会跳过
    # shutdown() 留下未释放的连接与后台任务; POSIX 信号路径 (serve_forever 正常
    # 返回) 行为不变。
    try:
        await runtime.serve_forever()
    finally:
        await runtime.shutdown()
        logger.info("ISAC 已退出")


def _register_usage_lifecycle(runtime: ApplicationRuntime, services: dict[str, Any]) -> None:
    """J1: 仅在启用计量时注册用量存储 + 周期性 flush 的生命周期。

    未启用计量 (usage_store 为 None) 时直接返回, 不注册任何生命周期, 主链路零变化。
    start: 先打开 DB 连接再启动周期任务 (避免周期任务第一次 tick 时连接还没就位);
    stop: 先停周期任务 (内部已含最终 flush) 再关连接, 顺序反过来会导致最后一批
    缓冲事件在落库前连接已关闭而丢失。
    """
    usage_store = services.get("usage_store")
    if usage_store is None:
        return
    usage_recorder = services.get("usage_recorder")

    async def _usage_start() -> None:
        await usage_store.start()
        if usage_recorder is not None:
            await usage_recorder.start()

    async def _usage_stop() -> None:
        if usage_recorder is not None:
            await usage_recorder.stop()
        await usage_store.stop()

    runtime.register_lifecycle("usage_store", _usage_start, _usage_stop)


def _register_subagent_lifecycle(runtime: ApplicationRuntime, services: dict[str, Any]) -> None:
    """J4: 仅在启用 subagent 日志时注册 Journal 生命周期。

    未启用 (subagent_journal 为 None) 时直接返回, 不创建任何 DB 文件。
    """
    journal = services.get("subagent_journal")
    if journal is None:
        return
    runtime.register_lifecycle("subagent_journal", journal.start, journal.stop)


async def _restore_subagent_interrupts(services: dict[str, Any]) -> None:
    """J4-3: SubAgent 重启恢复, 把 running/queued 标记为 cancelled。

    必须在 runtime.start() 之后调用 (subagent_journal 已 start, DB 连接就绪);
    journal 未启用或 supervisor 不存在时 no-op。
    """
    supervisor = services.get("subagent_supervisor")
    if supervisor is None:
        return
    try:
        marked = await supervisor.restore_interrupted()
        if marked > 0:
            logger.info("SubAgent 重启恢复: 已标记中断任务", marked=marked)
    except Exception as exc:  # noqa: BLE001
        logger.warning("SubAgent 重启恢复失败, 不阻塞启动", error=str(exc))


def _get_version() -> str:
    from isac import __version__

    return __version__


async def _load_persisted_links(bus: InterAgentBus, path: Path) -> None:
    """从 data/links.jsonc 恢复互联 Link (CODE_REVIEW_REPORT.md #3)。

    文件不存在或损坏时不阻塞启动; 损坏时仅记录 warning 并跳过, 让 in-memory 状态保持干净。
    """
    raw = await asyncio.to_thread(_read_links_file, path)
    if raw is None:
        return
    for item in raw.get("links", []) or []:
        try:
            bus.add_link(InterAgentLink(**item))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Link 恢复失败, 跳过该项", link=item, error=str(exc))


def _read_links_file(path: Path) -> dict | None:
    """同步读取并解析 links.jsonc; 不存在/损坏返回 None。

    拆成同步 helper 是为了让 async 调用方用 asyncio.to_thread 包装, 不在事件循环里
    直接执行 blocking IO (ruff ASYNC240)。
    """
    if not path.exists():
        return None
    try:
        try:
            import json5 as _json5

            return dict(_json5.loads(path.read_text(encoding="utf-8")))
        except ImportError:
            import json

            return dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001
        logger.warning("links.jsonc 解析失败, 跳过恢复", path=str(path), error=str(exc))
        return None
