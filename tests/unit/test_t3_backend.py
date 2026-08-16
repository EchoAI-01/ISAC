"""T3-backend: 控制面开箱后端支撑自检 (DEVELOPMENT_PLAN.md §四 T3-backend)。

覆盖:
- SetupManager: complete_setup / is_setup_required / is_password_valid / reset / 重启加载
- /setup API: GET 状态 / POST 设密码 / 重复 409 / 短密码 422
- auth 首登 gate: setup_enabled + 无凭证 → admin 端点 428 SETUP_REQUIRED; setup 后密码作 Bearer
- /api/v1/config/schema: 返回 JSON Schema
- CLI `isac password reset`
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


def _make_app(config_extra: dict[str, Any] | None = None, state_path: str | None = None) -> Any:
    """构造挂载 setup 路由的 control app (MagicMock 注入, setup_enabled=True)。"""
    from isac.control.api.server import create_control_app

    mock = MagicMock()
    config: dict[str, Any] = {
        "agents_dir": "data/agents",
        "routing_rules_path": "data/routing.jsonc",
        "links_path": "data/links.jsonc",
        "setup_enabled": True,
    }
    if state_path:
        config["setup_state_path"] = state_path
    if config_extra:
        config.update(config_extra)
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


# ── SetupManager 单元 ──────────────────────────────────────────


def test_setup_manager_lifecycle(tmp_path: Path) -> None:
    from isac.control.setup import SetupManager

    mgr = SetupManager(str(tmp_path / "setup_state.json"))
    assert mgr.is_setup_required is True
    with pytest.raises(ValueError):
        mgr.complete_setup("short")
    mgr.complete_setup("good-password-123")
    assert mgr.is_setup_required is False
    assert mgr.is_password_valid("good-password-123") is True
    assert mgr.is_password_valid("wrong") is False
    assert mgr.is_password_valid(None) is False
    # 重启: 新实例从文件加载已设密码
    mgr2 = SetupManager(str(tmp_path / "setup_state.json"))
    assert mgr2.is_setup_required is False
    assert mgr2.is_password_valid("good-password-123") is True
    mgr2.reset()
    assert mgr2.is_setup_required is True
    assert not (tmp_path / "setup_state.json").exists()


def test_setup_manager_corrupt_state_treated_as_unset(tmp_path: Path) -> None:
    from isac.control.setup import SetupManager

    state = tmp_path / "setup_state.json"
    state.write_text("{not valid json", encoding="utf-8")
    mgr = SetupManager(str(state))
    assert mgr.is_setup_required is True  # 损坏文件视为未设置


# ── /setup API ────────────────────────────────────────────────


def test_setup_status_and_complete(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(_make_app(state_path=str(tmp_path / "s.json")))
    r = client.get("/api/v1/setup")
    assert r.status_code == 200
    assert r.json()["setup_required"] is True
    # 短密码 → 422 (pydantic 层校验)
    assert client.post("/api/v1/setup", json={"password": "short"}).status_code == 422
    # 设密码 → 200
    r = client.post("/api/v1/setup", json={"password": "good-password-123"})
    assert r.status_code == 200
    assert r.json()["setup_required"] is False
    # 重复 setup → 409
    assert client.post("/api/v1/setup", json={"password": "good-password-123"}).status_code == 409


def test_setup_gate_blocks_admin_until_setup(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(_make_app(state_path=str(tmp_path / "s.json")))
    # 首登态: /api/v1/audit (admin) → 428 SETUP_REQUIRED
    r = client.get("/api/v1/audit")
    assert r.status_code == 428
    assert r.json()["detail"]["code"] == "SETUP_REQUIRED"
    # /health 仍可用 + 标记 setup_required
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["setup_required"] is True
    # setup 设密码
    client.post("/api/v1/setup", json={"password": "good-password-123"})
    # setup 后: 用该密码作 Bearer 访问 admin → 200
    r = client.get("/api/v1/audit", headers={"Authorization": "Bearer good-password-123"})
    assert r.status_code == 200
    # 错误密码 → 401
    assert client.get("/api/v1/audit", headers={"Authorization": "Bearer wrong"}).status_code == 401
    # 无 Bearer → 401 (setup 已完成, 不再 428)
    assert client.get("/api/v1/audit").status_code == 401


def test_config_schema_endpoint(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(_make_app(state_path=str(tmp_path / "s.json")))
    # 首登态 /config/schema 也是 admin → 428
    assert client.get("/api/v1/config/schema").status_code == 428
    client.post("/api/v1/setup", json={"password": "good-password-123"})
    r = client.get("/api/v1/config/schema", headers={"Authorization": "Bearer good-password-123"})
    assert r.status_code == 200
    schema = r.json()
    assert "properties" in schema
    assert "control" in schema["properties"]


# ── CLI password reset ────────────────────────────────────────


def test_cli_password_reset(tmp_path: Path) -> None:
    from isac.__main__ import _cmd_password_reset
    from isac.control.setup import SetupManager

    state = str(tmp_path / "s.json")
    # 未设置 → 无需重置 (exit 0)
    assert _cmd_password_reset(state) == 0
    # 设置密码
    mgr = SetupManager(state)
    mgr.complete_setup("good-password-123")
    assert mgr.is_setup_required is False
    assert Path(state).exists()
    # reset → exit 0 + 文件删除
    assert _cmd_password_reset(state) == 0
    assert not Path(state).exists()
    assert SetupManager(state).is_setup_required is True


# ── Fix-40: 已配静态凭证时 setup 通道关闭 (防未认证接管) ──


def test_setup_manager_static_credentials_disables_setup(tmp_path: Path) -> None:
    """Fix-40 单元: 已配 api_token/tokens 时 is_setup_required 恒 False 且
    complete_setup 拒绝 (PermissionError)。"""
    from isac.control.setup import SetupManager

    mgr = SetupManager(str(tmp_path / "s.json"), static_credentials_configured=True)
    assert mgr.has_static_credentials is True
    assert mgr.is_setup_required is False
    with pytest.raises(PermissionError):
        mgr.complete_setup("good-password-123")
    assert not (tmp_path / "s.json").exists()


def test_setup_endpoint_rejected_when_api_token_configured(tmp_path: Path) -> None:
    """Fix-40 端到端: 已配 api_token 但 setup_state 缺失 (新数据目录/CLI reset 后)
    时, 未认证 POST /setup 必须被拒 —— 此前攻击者可经此设置自己的密码并被 auth 层
    接受, 直接接管控制面。"""
    from fastapi.testclient import TestClient

    client = TestClient(_make_app(
        config_extra={"api_token": "tok-static"},
        state_path=str(tmp_path / "s.json"),
    ))
    r = client.post("/api/v1/setup", json={"password": "evil-password-123"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "SETUP_NOT_ALLOWED"
    # GET /setup: 有静态凭证 → setup_required=False
    assert client.get("/api/v1/setup").json()["setup_required"] is False
    # 攻击者密码不是有效凭证; 静态 token 正常可用
    assert client.get(
        "/api/v1/audit", headers={"Authorization": "Bearer evil-password-123"}
    ).status_code == 401
    assert client.get(
        "/api/v1/audit", headers={"Authorization": "Bearer tok-static"}
    ).status_code == 200
