"""Fix-17 会话 Cookie + CSRF 双提交校验 (CONTROL_PLANE_SPEC.md §8.2 第 5 条)。

覆盖:
- POST /auth/session: 合法 Bearer Token 换 Cookie 成功; 非法 Token 401; 未启用
  会话机制 (session_auth_enabled=False) 时 404
- 纯 Cookie (无 Authorization 头) 可以读资源
- 纯 Cookie 写请求缺 X-CSRF-Token 头 (或与 Cookie 不一致) → 403 CSRF_REQUIRED
- 纯 Cookie 写请求带正确 X-CSRF-Token 头 → 成功
- 纯 Bearer Header 认证的写请求不受 CSRF 校验影响 (向后兼容, 现有 API 客户端不用改)
- DELETE /auth/session 登出后 Cookie 认证立即失效
- Fix-12 的 tokens[] scope 模型下, 会话 Cookie 同样能通过 scope_dependency
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _make_app(config: dict | None = None, agents_dir: str = "data/agents") -> Any:
    from isac.control.api.server import create_control_app
    from isac.plugin.runtime.manager import PluginManager
    from isac.router.router import MessageRouter
    from isac.router.types import RoutingRules
    from isac.runtime.bus import InterAgentBus
    from isac.runtime.manager import AgentManager

    class _StubProviderManager:
        def for_agent(self, config: Any) -> None:
            return None

    class _StubMemory:
        def __init__(self, namespace: str) -> None:
            self.namespace = namespace

        async def search(self, *args: Any, **kwargs: Any) -> list:
            return []

        async def store_episode(self, *args: Any, **kwargs: Any) -> str:
            return ""

    services = {
        "global_config": {},
        "provider_manager": _StubProviderManager(),
        "memory_factory": lambda namespace: _StubMemory(namespace),
    }
    agent_manager = AgentManager(services)
    bus = InterAgentBus()
    router = MessageRouter(RoutingRules(), agents_provider=agent_manager.routing_infos)
    plugin_manager = PluginManager({})
    merged_config = dict(config if config is not None else {"api_token": "secret-token-123"})
    merged_config.setdefault("agents_dir", agents_dir)
    return create_control_app(
        agent_manager=agent_manager,
        router=router,
        bus=bus,
        plugin_manager=plugin_manager,
        config=merged_config,
    )


class TestAuthSessionEndpoint:
    def test_valid_token_returns_200_and_sets_cookies(self) -> None:
        client = TestClient(_make_app())
        response = client.post("/api/v1/auth/session", json={"token": "secret-token-123"})
        assert response.status_code == 200
        assert "isac_session" in client.cookies
        assert "csrf_token" in client.cookies

    def test_invalid_token_returns_401_and_sets_no_cookies(self) -> None:
        client = TestClient(_make_app())
        response = client.post("/api/v1/auth/session", json={"token": "wrong-token"})
        assert response.status_code == 401
        assert "isac_session" not in client.cookies

    def test_session_cookie_is_httponly(self) -> None:
        client = TestClient(_make_app())
        response = client.post("/api/v1/auth/session", json={"token": "secret-token-123"})
        set_cookie_headers = response.headers.get_list("set-cookie")
        session_header = next(h for h in set_cookie_headers if h.startswith("isac_session="))
        assert "HttpOnly" in session_header
        csrf_header = next(h for h in set_cookie_headers if h.startswith("csrf_token="))
        assert "HttpOnly" not in csrf_header

    def test_session_auth_disabled_returns_404(self) -> None:
        client = TestClient(_make_app({"api_token": "secret-token-123", "session_auth_enabled": False}))
        response = client.post("/api/v1/auth/session", json={"token": "secret-token-123"})
        assert response.status_code == 404

    def test_no_api_token_configured_means_no_session_endpoint(self) -> None:
        """开发模式 (未配置 api_token/tokens[]) 下认证本身就是跳过的, 会话 Cookie
        机制没有意义, /auth/session 不应该被挂载。"""
        client = TestClient(_make_app({}))
        response = client.post("/api/v1/auth/session", json={"token": "anything"})
        assert response.status_code == 404


class TestCookieAuthentication:
    def test_cookie_only_read_request_succeeds(self) -> None:
        client = TestClient(_make_app())
        client.post("/api/v1/auth/session", json={"token": "secret-token-123"})
        response = client.get("/api/v1/agents")
        assert response.status_code == 200

    def test_no_cookie_no_header_still_401(self) -> None:
        client = TestClient(_make_app())
        response = client.get("/api/v1/agents")
        assert response.status_code == 401

    def test_bearer_header_still_works_when_session_auth_enabled(self) -> None:
        """引入会话 Cookie 机制不能破坏现有纯 Bearer Header 认证路径。"""
        client = TestClient(_make_app())
        response = client.get(
            "/api/v1/agents", headers={"Authorization": "Bearer secret-token-123"}
        )
        assert response.status_code == 200

    def test_logout_invalidates_cookie_auth(self) -> None:
        client = TestClient(_make_app())
        client.post("/api/v1/auth/session", json={"token": "secret-token-123"})
        assert client.get("/api/v1/agents").status_code == 200
        client.delete("/api/v1/auth/session")
        assert client.get("/api/v1/agents").status_code == 401

    def test_tampered_session_cookie_rejected(self) -> None:
        client = TestClient(_make_app())
        client.post("/api/v1/auth/session", json={"token": "secret-token-123"})
        client.cookies.set("isac_session", "forged.signature")
        response = client.get("/api/v1/agents")
        assert response.status_code == 401


class TestCSRFProtection:
    def _login(self, client: TestClient) -> str:
        client.post("/api/v1/auth/session", json={"token": "secret-token-123"})
        return client.cookies["csrf_token"]

    def test_write_via_cookie_without_csrf_header_returns_403(self) -> None:
        client = TestClient(_make_app())
        self._login(client)
        response = client.post("/api/v1/agents", json={"agent_id": "csrf-missing"})
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "CSRF_REQUIRED"

    def test_write_via_cookie_with_mismatched_csrf_header_returns_403(self) -> None:
        client = TestClient(_make_app())
        self._login(client)
        response = client.post(
            "/api/v1/agents",
            json={"agent_id": "csrf-wrong"},
            headers={"X-CSRF-Token": "not-the-right-value"},
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "CSRF_REQUIRED"

    def test_write_via_cookie_with_matching_csrf_header_succeeds(self, tmp_path) -> None:
        client = TestClient(_make_app(agents_dir=str(tmp_path / "agents")))
        csrf = self._login(client)
        response = client.post(
            "/api/v1/agents",
            json={"agent_id": "csrf-ok"},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 200

    def test_write_via_bearer_header_does_not_require_csrf_token(self, tmp_path) -> None:
        """纯 API 客户端 (Bearer Header, 没有会话 Cookie) 不受 CSRF 校验影响,
        与之前的行为完全一致 (spec: "纯 API 客户端继续使用 Bearer Token")。"""
        client = TestClient(_make_app(agents_dir=str(tmp_path / "agents")))
        response = client.post(
            "/api/v1/agents",
            json={"agent_id": "bearer-write"},
            headers={"Authorization": "Bearer secret-token-123"},
        )
        assert response.status_code == 200

    def test_get_request_via_cookie_never_needs_csrf_token(self) -> None:
        client = TestClient(_make_app())
        self._login(client)
        response = client.get("/api/v1/agents")
        assert response.status_code == 200


class TestCSRFWithTokenScopeModel:
    """Fix-12 的 tokens[] scope 模型与 Fix-17 的会话 Cookie 机制必须协同工作:
    会话 Cookie 携带的是原始 token 字符串, scope_dependency 解析出的 caller 身份
    (及其 scope 集合) 必须与直接用 Authorization 头时一致。"""

    def test_scoped_token_session_cookie_respects_scope(self) -> None:
        client = TestClient(
            _make_app(
                {
                    "api_token": "fallback-admin",
                    "tokens": [{"token": "readonly", "scopes": ["agent:read"]}],
                }
            )
        )
        login = client.post("/api/v1/auth/session", json={"token": "readonly"})
        assert login.status_code == 200
        csrf = client.cookies["csrf_token"]

        read_resp = client.get("/api/v1/agents")
        assert read_resp.status_code == 200

        write_resp = client.post(
            "/api/v1/agents", json={"agent_id": "scoped-write"}, headers={"X-CSRF-Token": csrf}
        )
        assert write_resp.status_code == 403
        assert write_resp.json()["detail"]["code"] == "SCOPE_FORBIDDEN"
