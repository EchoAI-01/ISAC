"""N1e 全局配置持久化 + 热重载测试 (第三轮审查留档项落地)。

覆盖:
- utils/config: deep_merge_config 语义 / override 读写 round-trip / load_config
  加载序 (config.jsonc ← override ← 环境变量) / 损坏 override 硬失败。
- GET  /config/global: 敏感键脱敏 + revision 回显。
- PATCH /config/global: 校验先行不落盘 / override 持久化 / 原地热应用 /
  If-Match 409 / 哨兵剥离 / null 撤销覆盖 / restart_required 区分。
- POST /config/global/reload: 手编 config.jsonc 免重启生效。
- scope 门禁 (config:read / config:write) + 审计留痕 (只记节名不记值)。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from isac.control.api import routes_config
from isac.control.api.server import create_control_app
from isac.observability import get_default_metrics
from isac.utils.config import (
    deep_merge_config,
    load_config,
    load_config_overrides,
    save_config_overrides,
)

# ── utils/config 单元层 ──────────────────────────────────────────


def test_deep_merge_nested_and_delete() -> None:
    base = {"a": {"x": 1, "y": 2}, "keep": [1, 2]}
    patch = {"a": {"y": None, "z": 3}, "keep": [9]}
    merged = deep_merge_config(base, patch)
    assert merged == {"a": {"x": 1, "z": 3}, "keep": [9]}
    # 不改原对象
    assert base == {"a": {"x": 1, "y": 2}, "keep": [1, 2]}


def test_override_roundtrip_revision_and_delete(tmp_path: Path) -> None:
    path = tmp_path / "config.override.json"
    rev1 = save_config_overrides(path, {"llm": {"model": "m1"}})
    rev2 = save_config_overrides(path, {"llm": {"model": None, "api_key": "k"}})
    assert (rev1, rev2) == (1, 2)
    overrides, revision = load_config_overrides(path)
    assert revision == 2
    # model 被 None 删除, api_key 累积保留, __revision__ 不进配置
    assert overrides == {"llm": {"api_key": "k"}}
    assert "__revision__" not in json.loads(path.read_text(encoding="utf-8"))["llm"]


def test_load_config_overrides_missing_file(tmp_path: Path) -> None:
    overrides, revision = load_config_overrides(tmp_path / "nonexistent.json")
    assert overrides == {} and revision == 0


def test_load_config_overrides_corrupt_revision(tmp_path: Path) -> None:
    path = tmp_path / "config.override.json"
    path.write_text('{"__revision__": "abc"}', encoding="utf-8")
    with pytest.raises(ValueError, match="__revision__"):
        load_config_overrides(path)


def test_load_config_order_file_override_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """加载序: config.jsonc ← override ← 环境变量 (环境变量仍最高优先级)。"""
    cfg_path = tmp_path / "config.jsonc"
    cfg_path.write_text(
        '{"config_version": "1.0.0", "llm": {"model": "file-model", "provider": "openai-compat"}}',
        encoding="utf-8",
    )
    ov_path = tmp_path / "config.override.json"
    save_config_overrides(ov_path, {"llm": {"model": "override-model"}})

    cfg = load_config(cfg_path, override_path=ov_path)
    assert cfg["llm"]["model"] == "override-model"  # override 胜过 config.jsonc
    assert cfg["llm"]["provider"] == "openai-compat"  # 深合并不抹掉兄弟键

    monkeypatch.setenv("ISAC_LLM_MODEL", "env-model")
    cfg2 = load_config(cfg_path, override_path=ov_path)
    assert cfg2["llm"]["model"] == "env-model"  # 环境变量最高优先级不变


def test_load_config_with_inline_overrides(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.jsonc"
    cfg_path.write_text('{"config_version": "1.0.0", "bot_id": "file-bot"}', encoding="utf-8")
    cfg = load_config(cfg_path, overrides={"bot_id": "patch-bot"})
    assert cfg["bot_id"] == "patch-bot"


# ── 控制面端点层 ─────────────────────────────────────────────────


class _FakeAgentManager:
    """记录 reload_config 调用; running 实例会被热重载, stopped 跳过。"""

    def __init__(self, instances: list[Any] | None = None) -> None:
        self._instances = instances or []
        self.reloaded: list[str] = []

    async def list(self) -> list[Any]:
        return self._instances

    async def get(self, agent_id: str) -> Any:
        return None

    async def reload_config(self, agent_id: str, config: Any) -> None:
        self.reloaded.append(agent_id)


def _running(agent_id: str) -> SimpleNamespace:
    return SimpleNamespace(status="running", config=SimpleNamespace(agent_id=agent_id))


def _make_app(
    tmp_path: Path,
    global_config: dict[str, Any],
    am: _FakeAgentManager | None = None,
    api_token: str = "test-token",
    audit_log: Any = None,
) -> Any:
    cfg_path = tmp_path / "config.jsonc"
    if not cfg_path.exists():
        cfg_path.write_text('{"config_version": "1.0.0"}', encoding="utf-8")
    return create_control_app(
        am or _FakeAgentManager(), object(), object(), object(),
        {
            "api_token": api_token,
            "agents_dir": str(tmp_path / "agents"),
            "config_path": str(cfg_path),
            "config_override_path": str(tmp_path / "config.override.json"),
        },
        metrics=get_default_metrics(),
        services={"global_config": global_config},
        audit_log=audit_log,
    )


_AUTH = {"Authorization": "Bearer test-token"}


def test_get_global_config_redacts_and_reports_revision(tmp_path: Path) -> None:
    cfg = {"llm": {"api_key": "sk-secret-123", "model": "m"}, "control": {"api_token": "tok"}}
    app = _make_app(tmp_path, cfg)
    client = TestClient(app)
    resp = client.get("/api/v1/config/global", headers=_AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["revision"] == 0
    # 敏感键脱敏为哨兵, 明文绝不回显 (CONTROL_PLANE_SPEC §8.2 规则 4)
    assert data["config"]["llm"]["api_key"] == "__ISAC_REDACTED__"
    assert data["config"]["control"]["api_token"] == "__ISAC_REDACTED__"
    assert "sk-secret-123" not in resp.text
    # 非敏感键原样
    assert data["config"]["llm"]["model"] == "m"


def test_patch_persists_overrides_and_hot_applies(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.jsonc"
    # bot_id 放进文件 (生产语义: global_config 的每个值都有加载源, 无"纯内存值")
    cfg_path.write_text('{"config_version": "1.0.0", "bot_id": "b"}', encoding="utf-8")
    # 生产语义: global_config 是 load_config 产物 (含全部默认节), diff 才精确
    cfg = load_config(cfg_path)
    cfg["llm"]["model"] = "old"
    am = _FakeAgentManager([_running("a1"), SimpleNamespace(status="stopped", config=SimpleNamespace(agent_id="a2"))])
    app = _make_app(tmp_path, cfg, am=am)
    client = TestClient(app)

    resp = client.patch("/api/v1/config/global", json={"llm": {"model": "new"}}, headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] == ["llm"]
    assert body["restart_required"] == []
    assert body["reload_required"] == []
    assert body["revision"] == 1
    # running Agent 被重建, stopped 跳过
    assert am.reloaded == ["a1"]
    # 原地更新: 同一 dict 对象被更新 (services 持有者引用不变)
    assert cfg["llm"]["model"] == "new"
    assert cfg["bot_id"] == "b"
    # override 文件只含 patch 键 + revision (不回写整个有效配置)
    raw = json.loads((tmp_path / "config.override.json").read_text(encoding="utf-8"))
    assert raw == {"llm": {"model": "new"}, "__revision__": 1}


def test_patch_restart_required_sections_not_hot_applied(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.jsonc"
    cfg_path.write_text('{"config_version": "1.0.0"}', encoding="utf-8")
    cfg = load_config(cfg_path)
    am = _FakeAgentManager([_running("a1")])
    app = _make_app(tmp_path, cfg, am=am)
    client = TestClient(app)

    resp = client.patch(
        "/api/v1/config/global",
        json={"control": {"port": 9999}, "channels": {"webchat": {"enabled": False}}},
        headers=_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] == []
    assert sorted(body["restart_required"]) == ["channels", "control"]
    assert am.reloaded == []  # 纯重启节不触发 Agent 重建
    # 但已持久化 (下次重启生效)
    raw = json.loads((tmp_path / "config.override.json").read_text(encoding="utf-8"))
    assert raw["control"] == {"port": 9999}


def test_patch_invalid_config_rejected_without_persist(tmp_path: Path) -> None:
    cfg: dict[str, Any] = {"llm": {}}
    app = _make_app(tmp_path, cfg)
    client = TestClient(app)
    # control.port 越界 → schema 硬失败
    resp = client.patch("/api/v1/config/global", json={"control": {"port": 99999}}, headers=_AUTH)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "INVALID_CONFIG"
    assert not (tmp_path / "config.override.json").exists()  # 未落盘
    assert cfg.get("control", {}).get("port") != 99999  # 未热应用


def test_patch_if_match_conflict_and_success(tmp_path: Path) -> None:
    cfg: dict[str, Any] = {"bot_id": "b"}
    app = _make_app(tmp_path, cfg)
    client = TestClient(app)
    client.patch("/api/v1/config/global", json={"bot_id": "b1"}, headers=_AUTH)  # revision → 1

    # 过期 If-Match → 409 CONFIG_CONFLICT (J3-2 同构)
    resp = client.patch(
        "/api/v1/config/global", json={"bot_id": "b2"},
        headers={**_AUTH, "If-Match": "0"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "CONFIG_CONFLICT"
    assert resp.json()["detail"]["current_revision"] == 1

    # 正确 If-Match → 成功, revision +1
    resp = client.patch(
        "/api/v1/config/global", json={"bot_id": "b2"},
        headers={**_AUTH, "If-Match": "1"},
    )
    assert resp.status_code == 200
    assert resp.json()["revision"] == 2
    assert cfg["bot_id"] == "b2"


def test_patch_strips_redacted_sentinel(tmp_path: Path) -> None:
    """GET 脱敏值原样回传 = 未修改: 哨兵不落盘 (防哨兵当凭据透传)。"""
    cfg = {"llm": {"api_key": "real-key"}}
    app = _make_app(tmp_path, cfg)
    client = TestClient(app)

    # 纯哨兵 patch → 无有效变更 → 400
    resp = client.patch(
        "/api/v1/config/global", json={"llm": {"api_key": "__ISAC_REDACTED__"}}, headers=_AUTH
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "INVALID_INPUT"

    # 混合 patch: 哨兵剥离, 真值保留
    resp = client.patch(
        "/api/v1/config/global",
        json={"llm": {"api_key": "__ISAC_REDACTED__", "model": "m2"}},
        headers=_AUTH,
    )
    assert resp.status_code == 200
    raw = json.loads((tmp_path / "config.override.json").read_text(encoding="utf-8"))
    assert raw["llm"] == {"model": "m2"}  # 哨兵未落盘


def test_patch_null_removes_override_key(tmp_path: Path) -> None:
    """叶值 null = 撤销覆盖项, 回落到 config.jsonc 的值。"""
    cfg_path = tmp_path / "config.jsonc"
    cfg_path.write_text('{"config_version": "1.0.0", "bot_id": "file-bot"}', encoding="utf-8")
    cfg = {"bot_id": "file-bot"}
    app = _make_app(tmp_path, cfg)
    client = TestClient(app)

    client.patch("/api/v1/config/global", json={"bot_id": "patch-bot"}, headers=_AUTH)
    assert cfg["bot_id"] == "patch-bot"

    resp = client.patch("/api/v1/config/global", json={"bot_id": None}, headers=_AUTH)
    assert resp.status_code == 200
    assert cfg["bot_id"] == "file-bot"  # 回落到 config.jsonc
    raw = json.loads((tmp_path / "config.override.json").read_text(encoding="utf-8"))
    assert "bot_id" not in raw


def test_reload_picks_up_manual_config_edit(tmp_path: Path) -> None:
    """POST /config/global/reload: 手编 config.jsonc 后免重启生效。"""
    cfg_path = tmp_path / "config.jsonc"
    cfg_path.write_text('{"config_version": "1.0.0", "bot_id": "v1"}', encoding="utf-8")
    cfg = load_config(cfg_path)  # 生产语义: 启动时 load_config 产物
    am = _FakeAgentManager([_running("a1")])
    app = _make_app(tmp_path, cfg, am=am)
    client = TestClient(app)

    cfg_path.write_text('{"config_version": "1.0.0", "bot_id": "v2"}', encoding="utf-8")
    resp = client.post("/api/v1/config/global/reload", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] == ["bot_id"]
    assert cfg["bot_id"] == "v2"
    assert am.reloaded == ["a1"]


def test_reload_invalid_file_400(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.jsonc"
    cfg_path.write_text('{"config_version": "1.0.0"}', encoding="utf-8")
    cfg: dict[str, Any] = {}
    app = _make_app(tmp_path, cfg)
    client = TestClient(app)

    cfg_path.write_text('{"config_version": "1.0.0", "control": {"port": -1}}', encoding="utf-8")
    resp = client.post("/api/v1/config/global/reload", headers=_AUTH)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "INVALID_CONFIG"


def test_auth_required(tmp_path: Path) -> None:
    app = _make_app(tmp_path, {})
    client = TestClient(app)
    assert client.get("/api/v1/config/global").status_code in (401, 403)
    assert client.patch("/api/v1/config/global", json={"bot_id": "x"}).status_code in (401, 403)


def test_scope_gating_read_write() -> None:
    """config:read 可读不可写; config:write 可写; "*" 全通。"""
    from isac.control.auth import (
        make_scope_dependency_factory,
        make_token_only_dependency,
        parse_token_scopes,
    )

    parsed = parse_token_scopes({"tokens": [
        {"token": "admin", "scopes": ["*"]},
        {"token": "reader", "scopes": ["config:read"]},
        {"token": "writer", "scopes": ["config:write"]},
    ]})
    auth = make_token_only_dependency(parsed)
    scope = make_scope_dependency_factory(parsed)

    cfg: dict[str, Any] = {"bot_id": "b"}
    app = FastAPI()
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "config.jsonc"
        cfg_path.write_text('{"config_version": "1.0.0"}', encoding="utf-8")
        app.include_router(
            routes_config.build_router(
                auth_dependency=auth,
                agent_manager=_FakeAgentManager(),
                global_config=cfg,
                config_path=cfg_path,
                override_path=Path(td) / "config.override.json",
                scope_dependency=scope,
            ),
            prefix="/api/v1",
        )
        client = TestClient(app)

        assert client.get("/api/v1/config/global", headers={"Authorization": "Bearer reader"}).status_code == 200
        resp = client.patch(
            "/api/v1/config/global", json={"bot_id": "x"},
            headers={"Authorization": "Bearer reader"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "SCOPE_FORBIDDEN"
        # writer 可写
        resp = client.patch(
            "/api/v1/config/global", json={"bot_id": "x"},
            headers={"Authorization": "Bearer writer"},
        )
        assert resp.status_code == 200
        # admin 通配可读可写
        assert client.get("/api/v1/config/global", headers={"Authorization": "Bearer admin"}).status_code == 200


class _RecordingAudit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


def test_audit_records_sections_not_values(tmp_path: Path) -> None:
    """审计留痕只记变更节名, 绝不记值 (值可能含凭据)。"""
    audit = _RecordingAudit()
    cfg: dict[str, Any] = {"llm": {}}
    app = _make_app(tmp_path, cfg, audit_log=audit)
    client = TestClient(app)

    resp = client.patch(
        "/api/v1/config/global", json={"llm": {"api_key": "super-secret-value"}}, headers=_AUTH
    )
    assert resp.status_code == 200
    assert len(audit.records) == 1
    rec = audit.records[0]
    assert rec["action"] == "patch_global_config"
    assert rec["target"] == "global_config"
    assert "llm" in rec["detail"]
    assert "super-secret-value" not in json.dumps(rec, ensure_ascii=False)


def test_patch_accumulates_across_calls(tmp_path: Path) -> None:
    """连续 PATCH 累积 (read-modify-write), revision 单调。"""
    cfg: dict[str, Any] = {"llm": {}, "bot_id": "b"}
    app = _make_app(tmp_path, cfg)
    client = TestClient(app)

    r1 = client.patch("/api/v1/config/global", json={"llm": {"model": "m1"}}, headers=_AUTH)
    r2 = client.patch("/api/v1/config/global", json={"bot_id": "b2"}, headers=_AUTH)
    assert r1.json()["revision"] == 1
    assert r2.json()["revision"] == 2
    raw = json.loads((tmp_path / "config.override.json").read_text(encoding="utf-8"))
    assert raw["llm"] == {"model": "m1"} and raw["bot_id"] == "b2"


def test_secret_prefix_stays_in_override_not_resolved_on_disk(tmp_path: Path) -> None:
    """override 落盘保留 secret: 原值; 解析只发生在内存候选 (不落明文)。"""
    cfg: dict[str, Any] = {"llm": {}}
    app = _make_app(tmp_path, cfg)
    client = TestClient(app)

    resp = client.patch(
        "/api/v1/config/global", json={"llm": {"api_key": "secret:my-key"}}, headers=_AUTH
    )
    assert resp.status_code == 200
    raw_text = (tmp_path / "config.override.json").read_text(encoding="utf-8")
    assert "secret:my-key" in raw_text  # 原样持久化
