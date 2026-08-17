"""ISAC 主入口 (U2 薄入口)。

U2 装配层重构: 原 2000+ 行 main.py 拆分为 ——
- isac/dispatch.py   消息主链路 (process_message / make_message_dispatcher)
- isac/wiring.py     服务装配 (build_services 与服务构造器)
- isac/bootstrap.py  应用启动编排 (main 运行时生命周期)
- isac/control/bootstrap.py / isac/runtime/plugin_bootstrap.py /
  isac/channel/registration.py / isac/runtime/mesh/query.py /
  isac/memory/stack.py / isac/observability/usage/stack.py  卫星装配模块

本文件保留 re-export 兼容面 (既有 `from isac.main import ...` 调用方不变);
新代码请直接从上述模块导入。CLI 入口见 isac/__main__.py。
"""

from __future__ import annotations

from pathlib import Path

# 数据目录 (兼容旧导入; 各拆分模块内部各自持有同一相对路径常量)
DATA_DIR = Path("data")

# ── dispatch: 消息主链路 ─────────────────────────────────────
# ── bootstrap: 启动编排 ──────────────────────────────────────
from isac.bootstrap import (  # noqa: E402,F401
    _close_storage_stores,
    _ensure_data_dirs,
    _get_version,
    _load_persisted_links,
    _read_links_file,
    _register_subagent_lifecycle,
    _register_usage_lifecycle,
    _restore_subagent_interrupts,
    _start_session_event_store,
    main,
)
from isac.channel.registration import (  # noqa: E402,F401
    _ensure_default_routing,
    _register_channel_adapters,
)
from isac.control.bootstrap import _register_control_plane, _setup_webhooks  # noqa: E402,F401
from isac.dispatch import (  # noqa: E402,F401
    _append_artifact_segments,
    _apply_mesh_routing,
    _build_identity_resolver,
    _download_inbound_media_safe,
    _make_progress_sender,
    _maybe_consume_approval_reply,
    _resolve_artifact_store,
    _resolve_identity,
    _send_reply,
    _shutdown_message_pipeline,
    make_message_dispatcher,
    process_message,
)

# ── 卫星装配模块 ─────────────────────────────────────────────
from isac.memory.stack import _build_memory_stack  # noqa: E402,F401
from isac.runtime.mesh.query import _answer_memory_query  # noqa: E402,F401
from isac.runtime.plugin_bootstrap import (  # noqa: E402,F401
    _adapt_compat_plugins,
    _adapt_one_compat_plugin,
    _build_plugin_enable_matrix,
    _build_workflow_engine,
    _fire_plugin_on_load,
    _register_mcp_server,
    _run_compat_adapt,
)

# ── wiring: 服务装配 ─────────────────────────────────────────
from isac.wiring import (  # noqa: E402,F401
    _build_media_normalizer,
    _build_multimodal_provider,
    _build_secret_store,
    _build_session_history_kernel,
    _build_tenant_manager,
    _build_tool_permission_pipeline,
    _build_usage_stack,
    _wire_llm_capabilities,
    build_services,
    register_llm_provider,
    register_multimodal_providers,
)
