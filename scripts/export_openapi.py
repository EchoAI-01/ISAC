#!/usr/bin/env python3
"""FE0: 导出控制面 OpenAPI 契约基线到 docs/api/openapi.json。

用最小 mock 注入 create_control_app, 让全部按 manager 是否 None 决定挂载的
可选路由 (usage/subagent/providers/sessions/memory/events/workflows/identity/logs)
全部挂载, dump OpenAPI schema 作为前后端分离的 API 契约基线。

契约冻结策略 (见 docs/api.md):
- 运行时 /openapi.json 按 R15 默认关闭 (docs_enabled=False), 防误暴露完整端点列表。
- 契约基线以本脚本导出的 docs/api/openapi.json 文件为准 (归档进版本库)。
- 任何 API 变更后须重跑本脚本刷新基线, 否则前后端契约漂移。

用法:
    uv run python scripts/export_openapi.py
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from isac.control.api.server import create_control_app


def main() -> int:
    # MagicMock 让所有按 manager 是否 None 决定挂载的可选路由全部挂载,
    # 导出最完整的契约形态 (与生产配置全部启用时一致)。
    mock = MagicMock()
    config = {
        "api_token": "contract-export-placeholder",
        "agents_dir": "data/agents",
        "routing_rules_path": "data/routing.jsonc",
        "links_path": "data/links.jsonc",
        # setup_enabled=True 让 /setup 路由挂载进契约 (T3-backend); state_path 用
        # 不存在的临时路径, SetupManager 读不到文件 → is_setup_required=True,
        # 不影响路由结构导出, 也不会在导出时创建真实状态文件。
        "setup_enabled": True,
        "setup_state_path": "/tmp/isac_openapi_export_setup_state.json",
    }
    app = create_control_app(
        agent_manager=mock,
        router=mock,
        bus=mock,
        plugin_manager=mock,
        config=config,
        metrics=mock,
        usage_store=mock,
        subagent_supervisor=mock,
        provider_manager=mock,
        model_catalog=mock,
        artifact_store=mock,
        session_manager=mock,
        metadata_store=mock,
        event_bus=mock,
        sparse_resolver=mock,
        workflow_engine=mock,
        identity_resolver=mock,
        vector_resolver=mock,
        channel_registry=mock,
    )
    schema = app.openapi()
    out = Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    paths = schema.get("paths", {})
    print(f"[export] OpenAPI 契约基线已导出: {out}")
    print(f"[export] {len(paths)} 个路径, version={schema.get('info', {}).get('version')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
