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
        # N1e: 注入 global_config 使 /config/global 系列端点进契约 (与导出脚本一致)。
        services={"global_config": {}},
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
    """运行时 openapi paths 必须与归档基线一致; 漂移则提示重跑导出脚本刷新基线。

    N4 (2026-10-11): 基线允许包含运行时 openapi() 之外的**静态挂载补充条目**
    (/ui/ 等 Starlette Mount, include_in_schema=False 不进 openapi) —— 判定改为
    运行时 ⊆ 基线 且 基线无未知补充 (补充条目仅限 /ui/, 防误增)。
    """
    runtime_paths = set(_make_full_app().openapi()["paths"].keys())  # type: ignore[union-attr]
    baseline_paths = set(baseline["paths"].keys())
    allowed_extra = {"/ui/"}  # 导出脚本注入的静态挂载描述条目
    unexpected = baseline_paths - runtime_paths - allowed_extra
    assert not (runtime_paths - baseline_paths), (
        "运行时端点未入基线 (跑 scripts/export_openapi.py 刷新): "
        f"仅运行时={runtime_paths - baseline_paths}"
    )
    assert not unexpected, (
        f"基线含未知补充条目 (仅允许静态挂载 {sorted(allowed_extra)}): {unexpected}; "
        "跑 scripts/export_openapi.py 刷新基线"
    )


def test_baseline_has_security_schemes(baseline: dict) -> None:
    """N4: securitySchemes 必须齐备 (前端生成客户端的认证对接前提)。"""
    schemes = baseline.get("components", {}).get("securitySchemes", {})
    assert "bearerAuth" in schemes, "基线缺 bearerAuth securityScheme"
    assert "sessionAuth" in schemes, "基线缺 sessionAuth securityScheme"
    assert baseline.get("security"), "基线缺顶层 security 声明"


def test_config_schema_covers_all_top_level_keys() -> None:
    """N4: /api/v1/config/schema 的模型必须覆盖 config.sample.jsonc 全部顶层键。

    此前 ISACConfig 仅 3 键 (debug/log_level/control), 前端表单驱动前提不成立。
    """
    import re

    from isac.utils.config_schema import ISACConfig

    sample_raw = (Path(__file__).resolve().parents[2] / "data" / "config.sample.jsonc").read_text(
        encoding="utf-8"
    )
    sample_keys = set(re.findall(r'^  "?([A-Za-z_][A-Za-z0-9_]*)"?\s*:', sample_raw, re.M))
    schema_keys = set(ISACConfig.model_json_schema().get("properties", {}).keys())
    missing = sample_keys - schema_keys
    assert not missing, f"config schema 未覆盖 sample 顶层键: {sorted(missing)}"
    # 每键必须带 description (前端表单标签/提示的最低要求)。
    for key, prop in ISACConfig.model_json_schema().get("properties", {}).items():
        assert prop.get("description"), f"config schema 键 {key} 缺 description"
