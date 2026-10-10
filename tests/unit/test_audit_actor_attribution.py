"""#29 审计 actor 归因测试: 依赖返回可区分身份 + 路由审计记录真实 actor。

背景: 控制面 ~8 个路由审计日志 actor 恒硬编码 "authenticated", 无法回答"谁做的";
auth 依赖恒返回 "authenticated" 或裸 token (后者若落审计即泄露凭据)。

验收:
- actor_for_token: 有 name → token:<name>; 无 name → token:<tok-指纹> (不可逆);
- make_auth_dependency: header 命中 → api_token; setup 密码 → setup_password;
- make_token_only_dependency / scope 依赖: 返回掩码 actor, 绝不返回裸 token;
- 路由审计记录真实 actor (端到端经 TestClient)。
"""

from __future__ import annotations

import pytest

from isac.control.auth import (
    TokenScope,
    actor_for_token,
    make_auth_dependency,
    make_scope_dependency_factory,
    make_token_only_dependency,
    parse_token_scopes,
    token_fingerprint,
)

# ── actor_for_token ────────────────────────────────────────────


def test_actor_for_named_token() -> None:
    matched = TokenScope(token="secret-abc", scopes=frozenset({"*"}), name="ops-bot")
    assert actor_for_token(matched) == "token:ops-bot"


def test_actor_for_unnamed_token_uses_fingerprint() -> None:
    matched = TokenScope(token="secret-abc", scopes=frozenset({"*"}))
    actor = actor_for_token(matched)
    assert actor == f"token:{token_fingerprint('secret-abc')}"
    # 绝不泄露裸 token
    assert "secret-abc" not in actor


def test_actor_for_none_fallback() -> None:
    assert actor_for_token(None) == "authenticated"


def test_parse_token_scopes_reads_name() -> None:
    parsed = parse_token_scopes(
        {"tokens": [{"token": "t1", "scopes": ["agent:write"], "name": "ci"}]}
    )
    assert parsed is not None
    assert parsed[0].name == "ci"
    # 缺 name 默认空串
    parsed2 = parse_token_scopes({"tokens": [{"token": "t2", "scopes": []}]})
    assert parsed2 is not None and parsed2[0].name == ""


# ── make_auth_dependency: 区分凭据来源 ─────────────────────────


def test_auth_dependency_header_hit_returns_api_token() -> None:
    dep = make_auth_dependency("tok-123")
    assert dep(authorization="Bearer tok-123", session_cookie=None) == "api_token"


def test_auth_dependency_setup_password_returns_setup_password() -> None:
    class _Setup:
        is_setup_required = False

        def is_password_valid(self, token: str | None) -> bool:
            return token == "pw-hash"

    dep = make_auth_dependency("tok-123", setup_manager=_Setup())
    assert dep(authorization="Bearer pw-hash", session_cookie=None) == "setup_password"


def test_auth_dependency_anonymous_dev_mode() -> None:
    dep = make_auth_dependency("")  # 未配置 token 且无 setup → 开发模式
    assert dep(authorization=None, session_cookie=None) == "anonymous"


# ── make_token_only_dependency / scope 依赖: 掩码不落裸 token ──


def test_token_only_dependency_returns_masked_actor() -> None:
    tokens = [TokenScope(token="secret-xyz", scopes=frozenset({"*"}), name="ops")]
    dep = make_token_only_dependency(tokens)
    actor = dep(authorization="Bearer secret-xyz", session_cookie=None)
    assert actor == "token:ops"
    assert "secret-xyz" not in actor


def test_token_only_dependency_unnamed_token_masked_fingerprint() -> None:
    tokens = [TokenScope(token="secret-xyz", scopes=frozenset({"*"}))]
    dep = make_token_only_dependency(tokens)
    actor = dep(authorization="Bearer secret-xyz", session_cookie=None)
    assert actor.startswith("token:tok-")
    assert "secret-xyz" not in actor


def test_scope_dependency_returns_masked_actor() -> None:
    tokens = [TokenScope(token="secret-xyz", scopes=frozenset({"agent:write"}), name="ci")]
    factory = make_scope_dependency_factory(tokens)
    check = factory("agent:write")
    actor = check(authorization="Bearer secret-xyz", session_cookie=None)
    assert actor == "token:ci"
    assert "secret-xyz" not in actor


# ── 端到端: 路由审计记录真实 actor ─────────────────────────────


@pytest.mark.asyncio
async def test_workflow_route_audits_real_actor() -> None:
    """workflows start 端点经 _resolve_operator 记录真实调用方指纹 (非 authenticated)。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from isac.control.api import routes_workflows
    from isac.runtime.workflow.engine import WorkflowEngine
    from isac.runtime.workflow.models import Stage, Workflow

    class _RecordingAudit:
        def __init__(self) -> None:
            self.entries: list[dict] = []

        async def record(self, **kw) -> None:
            self.entries.append(kw)

    engine = WorkflowEngine()
    engine.register(Workflow(workflow_id="w1", name="t", stages=[Stage(stage_id="s1", action="noop")], transitions=[]))
    audit = _RecordingAudit()
    app = FastAPI()
    app.include_router(
        routes_workflows.build_router(engine, auth_dependency=lambda: "api_token", audit_log=audit),
        prefix="/api/v1",
    )
    client = TestClient(app)
    resp = client.post(
        "/api/v1/workflows/w1/start",
        headers={"Authorization": "Bearer caller-secret"},
    )
    assert resp.status_code == 200
    assert audit.entries, "start_workflow 应记录审计"
    actor = audit.entries[0]["actor"]
    # 真实调用方指纹 (tok- 前缀), 不再是恒 "authenticated"
    assert actor == token_fingerprint("caller-secret")
    assert actor != "authenticated"


@pytest.mark.asyncio
async def test_routing_route_audits_dependency_actor(tmp_path) -> None:
    """#29 新机制: handler 经 Depends(auth_dependency) 注入的 actor 写入审计。

    auth 依赖返回 "api_token" (make_auth_dependency header 命中语义), 审计 actor
    应为 "api_token" 而非恒 "authenticated"。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from isac.control.api import routes_routing
    from isac.router.router import MessageRouter
    from isac.router.rules import RoutingRules
    from isac.runtime.bus import InterAgentBus

    class _RecordingAudit:
        def __init__(self) -> None:
            self.entries: list[dict] = []

        async def record(self, **kw) -> None:
            self.entries.append(kw)

    router = MessageRouter(RoutingRules(), agents_provider=lambda: {})
    bus = InterAgentBus()
    audit = _RecordingAudit()
    app = FastAPI()
    app.include_router(
        routes_routing.build_router(
            router, bus,
            auth_dependency=lambda: "api_token",  # 模拟 make_auth_dependency header 命中
            audit_log=audit,
            routing_rules_path=str(tmp_path / "routing.jsonc"),
            links_path=str(tmp_path / "links.jsonc"),
        ),
        prefix="/api/v1",
    )
    client = TestClient(app)
    resp = client.put(
        "/api/v1/routing/rules",
        json={"bindings": [], "default_agents": {}},
        headers={"Authorization": "Bearer whatever"},
    )
    assert resp.status_code == 200
    assert audit.entries, "put_rules 应记录审计"
    assert audit.entries[0]["actor"] == "api_token"
    assert audit.entries[0]["actor"] != "authenticated"
