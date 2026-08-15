"""FE0: API 契约基线自检 (DEVELOPMENT_PLAN.md §四 FE0)。

验证:
- docs/api/openapi.json 归档文件可加载 + 结构正确 (paths 非空 + /api/v1 前缀)。
- 归档基线 version == isac.__version__。
- 关键端点存在 (/health, /api/v1/agents, /api/v1/audit)。
- 运行时 create_control_app 的 openapi() paths 与归档基线一致 —— 防 API 变更后
  忘记跑 scripts/export_openapi.py 刷新基线导致前后端契约漂移。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from isac import __version__

BASELINE_PATH = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"


def _make_full_app() -> object:
    """构造挂载全部可选路由的 control app (与 scripts/export_openapi.py 同逻辑)。"""
    from isac.control.api.server import create_control_app

    mock = MagicMock()
    config = {
        "api_token": "contract-test-placeholder",
        "agents_dir": "data/agents",
        "routing_rules_path": "data/routing.jsonc",
        "links_path": "data/links.jsonc",
        # 与 scripts/export_openapi.py 一致: 让 /setup 进契约基线 (T3-backend)。
        "setup_enabled": True,
        "setup_state_path": "/tmp/isac_openapi_export_setup_state.json",
    }
    return create_control_app(
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


@pytest.fixture(scope="module")
def baseline() -> dict:
    """加载归档契约基线 (缺失则提示先导出)。"""
    assert BASELINE_PATH.exists(), "契约基线 docs/api/openapi.json 缺失, 跑 scripts/export_openapi.py 生成"
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_baseline_loads_and_has_paths(baseline: dict) -> None:
    assert "paths" in baseline and baseline["paths"], "openapi 基线无 paths"
    assert baseline["info"]["version"] == __version__, "基线 version 与 isac.__version__ 不一致"


def test_baseline_has_v1_prefix_and_key_endpoints(baseline: dict) -> None:
    paths = baseline["paths"]
    assert any(p.startswith("/api/v1") for p in paths), "基线无 /api/v1 前缀端点"
    for key in ("/health", "/api/v1/agents", "/api/v1/audit"):
        assert key in paths, f"关键端点缺失: {key}"


def test_runtime_paths_match_baseline(baseline: dict) -> None:
    """运行时 openapi paths 必须与归档基线一致; 漂移则提示重跑导出脚本刷新基线。"""
    runtime_paths = set(_make_full_app().openapi()["paths"].keys())  # type: ignore[union-attr]
    baseline_paths = set(baseline["paths"].keys())
    assert runtime_paths == baseline_paths, (
        "运行时与归档基线 paths 漂移: "
        f"仅运行时={runtime_paths - baseline_paths}, "
        f"仅基线={baseline_paths - runtime_paths}; "
        "跑 scripts/export_openapi.py 刷新基线"
    )
