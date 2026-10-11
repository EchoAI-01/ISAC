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
        # N1e: 注入 global_config 使 /config/global 系列端点进入契约基线。
        services={"global_config": {}},
    )
    schema = app.openapi()
    # ── N4 API 基线缺口修复 (2026-10-11 审计) ──────────────────────
    # ① securitySchemes: 认证是自定义依赖 (不挂在 FastAPI Security 上), openapi()
    #    不会自动产出 —— 前端生成客户端无从得知认证方式。此处显式注入两种 scheme
    #    (Bearer Token / Session Cookie) 并设全局 security, 语义与
    #    CONTROL_PLANE_SPEC §6.1 (api_token/tokens[]) 及 §8.2 (会话 Cookie) 一致。
    components = schema.setdefault("components", {})
    components["securitySchemes"] = {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "description": "静态 Token: control.api_token 或 control.tokens[] 条目 "
            "(tokens[] 部署下按 scope 限权; 跨源前端写操作建议用此轨)。",
        },
        "sessionAuth": {
            "type": "apiKey",
            "in": "cookie",
            "name": "isac_session",
            "description": "会话 Cookie: POST /api/v1/auth/session 登录获得 (CSRF 双提交, "
            "同源部署 / CORS origins 放行时可用)。",
        },
    }
    schema["security"] = [{"bearerAuth": []}, {"sessionAuth": []}]
    info = schema.setdefault("info", {})
    info["description"] = (
        (info.get("description") or "")
        + "\n\n认证模型: 全部端点默认要求认证 —— Bearer Token (Authorization: Bearer <token>, "
        "control.api_token 或 control.tokens[], 见 CONTROL_PLANE_SPEC §6.1) 或会话 Cookie "
        "(POST /api/v1/auth/session, §8.2) 二选一; setup_enabled 首登流程见 POST /api/v1/setup。"
        "例外: /health 与 /metrics(text/plain) 免认证。"
    )
    # ② 生产挂载路径: WebUI 静态托管经 Starlette Mount + include_in_schema=False,
    #    不会出现在 openapi() 里 —— 前端按基线开发会漏。补描述性条目 (只描述形状,
    #    不参与代码生成校验)。
    paths = schema.setdefault("paths", {})
    paths.setdefault("/ui/", {
        "get": {
            "summary": "内置 WebUI 管理面板 (静态托管, deprecated — F2 迁移后移除)",
            "description": "浏览器打开 /ui/ 进入内置 WebUI (Vanilla JS SPA 十域)。"
            "FE1 起标 deprecated, 前端轨道 F2 完成后由独立前端项目取代并移除本挂载。",
            "responses": {"200": {"description": "WebUI HTML"}},
        }
    })
    out = Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[export] OpenAPI 契约基线已导出: {out}")
    print(
        f"[export] {len(paths)} 个路径, securitySchemes=bearerAuth+sessionAuth, "
        f"version={schema.get('info', {}).get('version')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
