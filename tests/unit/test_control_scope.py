"""Fix-12: 控制面 Token Scope 模型。

CONTROL_PLANE_SPEC.md §6.1 描述了按 scope 收窄 Token 权限的模型 (示例:
usage:read/usage:detail/agent:read/agent:write/...), 但此前控制面所有路由都
只有一个扁平 Bearer Token (要么全权限要么拒绝), 代码里没有任何地方真正实现
过按 scope 校验。

本模块新增 control.tokens[] 配置 (每项 {token, scopes})、解析函数与按需求
scope 构造 FastAPI 依赖的工厂; 未配置 tokens[] 时行为完全不变 (向后兼容现有
单一 api_token 扁平认证, 不引入任何强制性变化)。
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from isac.control.auth import make_scope_dependency_factory, parse_token_scopes


def test_parse_token_scopes_returns_none_when_not_configured() -> None:
    """未配置 tokens[] 时返回 None, 调用方应回退到现有扁平 api_token 认证。"""
    assert parse_token_scopes({}) is None
    assert parse_token_scopes({"api_token": "secret"}) is None


def test_parse_token_scopes_parses_entries() -> None:
    parsed = parse_token_scopes({
        "tokens": [
            {"token": "admin-token", "scopes": ["*"]},
            {"token": "readonly-token", "scopes": ["usage:read"]},
        ]
    })
    assert parsed is not None
    by_token = {t.token: t.scopes for t in parsed}
    assert by_token["admin-token"] == frozenset({"*"})
    assert by_token["readonly-token"] == frozenset({"usage:read"})


def test_parse_token_scopes_skips_entries_without_token() -> None:
    parsed = parse_token_scopes({"tokens": [{"scopes": ["usage:read"]}]})
    assert parsed is None


def _make_test_app(tokens) -> FastAPI:
    factory = make_scope_dependency_factory(tokens)
    app = FastAPI()

    @app.get("/read-only", dependencies=[Depends(factory("usage:read"))])
    async def read_only() -> dict:
        return {"ok": True}

    @app.get("/detail", dependencies=[Depends(factory("usage:detail"))])
    async def detail() -> dict:
        return {"ok": True}

    return app


def test_scope_dependency_allows_matching_scope() -> None:
    tokens = parse_token_scopes({"tokens": [{"token": "t1", "scopes": ["usage:read"]}]})
    client = TestClient(_make_test_app(tokens))
    resp = client.get("/read-only", headers={"Authorization": "Bearer t1"})
    assert resp.status_code == 200


def test_scope_dependency_rejects_insufficient_scope() -> None:
    """readonly token 只有 usage:read, 访问需要 usage:detail 的端点必须 403。"""
    tokens = parse_token_scopes({"tokens": [{"token": "t1", "scopes": ["usage:read"]}]})
    client = TestClient(_make_test_app(tokens))
    resp = client.get("/detail", headers={"Authorization": "Bearer t1"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "SCOPE_FORBIDDEN"


def test_scope_dependency_wildcard_scope_grants_everything() -> None:
    tokens = parse_token_scopes({"tokens": [{"token": "admin", "scopes": ["*"]}]})
    client = TestClient(_make_test_app(tokens))
    resp = client.get("/detail", headers={"Authorization": "Bearer admin"})
    assert resp.status_code == 200


def test_scope_dependency_rejects_unknown_token() -> None:
    tokens = parse_token_scopes({"tokens": [{"token": "t1", "scopes": ["*"]}]})
    client = TestClient(_make_test_app(tokens))
    resp = client.get("/read-only", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


def test_scope_dependency_rejects_missing_token() -> None:
    tokens = parse_token_scopes({"tokens": [{"token": "t1", "scopes": ["*"]}]})
    client = TestClient(_make_test_app(tokens))
    resp = client.get("/read-only")
    assert resp.status_code == 401
