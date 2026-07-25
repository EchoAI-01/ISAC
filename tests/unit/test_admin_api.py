"""G1 Admin API 测试 - Token 认证 + 审计日志 + 持久化。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def control_app(tmp_path: Path):
    """构造一个配置好的 FastAPI TestClient。"""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi 未安装")
    from isac.control.api.server import create_control_app
    from isac.plugin.runtime.manager import PluginManager
    from isac.router.router import MessageRouter
    from isac.router.types import RoutingRules
    from isac.runtime.bus import InterAgentBus
    from isac.runtime.manager import AgentManager

    services = {
        "global_config": {},
        "provider_manager": _StubProviderManager(),
        "memory_factory": lambda namespace: _StubMemory(namespace),
    }
    agent_manager = AgentManager(services)
    bus = InterAgentBus()
    router = MessageRouter(RoutingRules(), agents_provider=agent_manager.routing_infos)
    plugin_manager = PluginManager({})

    app = create_control_app(
        agent_manager=agent_manager,
        router=router,
        bus=bus,
        plugin_manager=plugin_manager,
        config={
            "api_token": "secret-token-123",
            "agents_dir": str(tmp_path / "agents"),
            "routing_rules_path": str(tmp_path / "routing.jsonc"),
            "links_path": str(tmp_path / "links.jsonc"),
            "audit_log_path": str(tmp_path / "audit.ndjson"),
        },
    )
    return TestClient(app), tmp_path


class _StubProviderManager:
    def for_agent(self, config):
        return None


class _StubMemory:
    def __init__(self, namespace):
        self.namespace = namespace

    async def search(self, *args, **kwargs):
        return []

    async def store_episode(self, *args, **kwargs):
        return ""


class TestTokenAuth:
    def test_missing_token_returns_401(self, control_app) -> None:
        client, _ = control_app
        response = client.get("/api/v1/agents")
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "UNAUTHORIZED"

    def test_wrong_token_returns_401(self, control_app) -> None:
        client, _ = control_app
        response = client.get(
            "/api/v1/agents",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401

    def test_correct_token_passes(self, control_app) -> None:
        client, _ = control_app
        response = client.get(
            "/api/v1/agents",
            headers={"Authorization": "Bearer secret-token-123"},
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_audit_endpoint_requires_token(self, control_app) -> None:
        client, _ = control_app
        response = client.get("/api/v1/audit")
        assert response.status_code == 401

    def test_json_metrics_endpoint_requires_token(self, control_app) -> None:
        client, _ = control_app
        response = client.get("/api/v1/metrics")
        assert response.status_code == 401

    def test_prometheus_metrics_endpoint_stays_unauthenticated(self, control_app) -> None:
        """/metrics (无 /api/v1 前缀) 是刻意开放给 Prometheus 抓取的，不应加认证。"""
        client, _ = control_app
        response = client.get("/metrics")
        assert response.status_code == 200


class TestAgentLifecycleWithAudit:
    def test_create_agent_persists_config(self, control_app) -> None:
        client, tmp_path = control_app
        response = client.post(
            "/api/v1/agents",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"agent_id": "test_agent", "display_name": "测试 Agent"},
        )
        assert response.status_code == 200
        assert response.json() == {"agent_id": "test_agent", "status": "stopped"}
        # 验证持久化
        assert (tmp_path / "agents" / "test_agent" / "config.jsonc").exists()

    def test_create_agent_logs_audit(self, control_app) -> None:
        client, tmp_path = control_app
        client.post(
            "/api/v1/agents",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"agent_id": "audit_target", "display_name": "审计目标"},
        )
        # 验证审计日志文件
        audit_content = (tmp_path / "audit.ndjson").read_text(encoding="utf-8")
        assert "create_agent" in audit_content
        assert "audit_target" in audit_content

    def test_query_audit_endpoint(self, control_app) -> None:
        client, _ = control_app
        client.post(
            "/api/v1/agents",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"agent_id": "a1", "display_name": "A1"},
        )
        client.post(
            "/api/v1/agents",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"agent_id": "a2", "display_name": "A2"},
        )
        response = client.get(
            "/api/v1/audit?action=create_agent",
            headers={"Authorization": "Bearer secret-token-123"},
        )
        assert response.status_code == 200
        entries = response.json()
        assert len(entries) == 2
        assert all(e["action"] == "create_agent" for e in entries)


class TestPatchAgentIfMatch:
    """Fix-11: PATCH /agents/{id} 的 If-Match 乐观锁必须真正读 HTTP Header
    (CONTROL_PLANE_SPEC.md 规范的方式), 而不是只认 ?if_match= query 参数。

    save_agent_config() 每次保存都 +1 revision (isac/runtime/config.py), 所以
    create() 落盘一次后 revision 已经是 2, 不是 dataclass 默认值 1。
    """

    def _create(self, client, agent_id: str = "patch-target") -> None:
        response = client.post(
            "/api/v1/agents",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"agent_id": agent_id, "display_name": "Before"},
        )
        assert response.status_code == 200

    def test_patch_with_correct_if_match_header_succeeds(self, control_app) -> None:
        client, _ = control_app
        self._create(client)
        response = client.patch(
            "/api/v1/agents/patch-target",
            headers={"Authorization": "Bearer secret-token-123", "If-Match": "2"},
            json={"display_name": "After"},
        )
        assert response.status_code == 200
        assert response.json()["revision"] == 3

    def test_patch_with_stale_if_match_header_returns_409(self, control_app) -> None:
        """之前 if_match 是 query 参数, HTTP Header 会被静默忽略、PATCH 无条件
        覆盖; 修复后必须真正读 Header 并在版本不匹配时拒绝。"""
        client, _ = control_app
        self._create(client)
        response = client.patch(
            "/api/v1/agents/patch-target",
            headers={"Authorization": "Bearer secret-token-123", "If-Match": "99"},
            json={"display_name": "Should not apply"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "CONFIG_CONFLICT"

    def test_patch_with_legacy_query_param_still_works(self, control_app) -> None:
        """向后兼容: WebUI 目前仍用 ?if_match= query 参数, Header 缺失时应回退到它。"""
        client, _ = control_app
        self._create(client)
        response = client.patch(
            "/api/v1/agents/patch-target?if_match=2",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"display_name": "After"},
        )
        assert response.status_code == 200
        assert response.json()["revision"] == 3

    def test_patch_header_takes_precedence_over_stale_query_param(self, control_app) -> None:
        """Header 优先于 query 参数 (防止两者不一致时产生歧义)。"""
        client, _ = control_app
        self._create(client)
        response = client.patch(
            "/api/v1/agents/patch-target?if_match=2",
            headers={"Authorization": "Bearer secret-token-123", "If-Match": "99"},
            json={"display_name": "After"},
        )
        assert response.status_code == 409


class TestRoutingAndLinks:
    def test_put_rules_persists(self, control_app) -> None:
        client, tmp_path = control_app
        response = client.put(
            "/api/v1/routing/rules",
            headers={"Authorization": "Bearer secret-token-123"},
            json={
                "bindings": [
                    {"platform": "qq", "agent_id": "default", "group_id": None, "user_id": None}
                ],
                "default_agents": {"qq": "default"},
            },
        )
        assert response.status_code == 200
        # 验证 routing.jsonc 持久化
        rules_file = tmp_path / "routing.jsonc"
        assert rules_file.exists()
        content = rules_file.read_text(encoding="utf-8")
        assert "default" in content

    def test_add_link_persists(self, control_app) -> None:
        client, tmp_path = control_app
        response = client.post(
            "/api/v1/links",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"from_agent": "a", "to_agent": "b", "direction": "both"},
        )
        assert response.status_code == 200
        assert (tmp_path / "links.jsonc").exists()
        content = (tmp_path / "links.jsonc").read_text(encoding="utf-8")
        assert "from_agent" in content and "\"a\"" in content

    def test_add_link_returns_500_when_persist_fails(self, monkeypatch, control_app) -> None:
        """写盘失败时 API 返回 500, 调用方能感知磁盘/内存态不一致 (CODE_REVIEW_REPORT.md #20)。"""
        import isac.utils.fs as fs

        client, _ = control_app

        def _raise(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(fs, "atomic_write_text", _raise)
        response = client.post(
            "/api/v1/links",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"from_agent": "a", "to_agent": "b"},
        )
        assert response.status_code == 500
        assert response.json()["detail"]["code"] == "LINK_PERSIST_FAILED"


class TestAgentIdValidation:
    def test_path_traversal_agent_id_rejected(self, control_app) -> None:
        client, tmp_path = control_app
        response = client.post(
            "/api/v1/agents",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"agent_id": "../escaped"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_CONFIG"
        assert not (tmp_path / "escaped").exists()
        assert not (tmp_path / "agents" / ".." / "escaped").exists()

    def test_empty_agent_id_rejected(self, control_app) -> None:
        client, _ = control_app
        response = client.post(
            "/api/v1/agents",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"agent_id": ""},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_CONFIG"

    def test_agent_id_with_slash_rejected(self, control_app) -> None:
        client, tmp_path = control_app
        response = client.post(
            "/api/v1/agents",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"agent_id": "foo/bar"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_CONFIG"
        assert not (tmp_path / "agents" / "foo").exists()

    def test_overlong_agent_id_rejected(self, control_app) -> None:
        client, _ = control_app
        response = client.post(
            "/api/v1/agents",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"agent_id": "a" * 65},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_CONFIG"

    def test_valid_agent_id_with_underscore_and_dash_accepted(self, control_app) -> None:
        client, _ = control_app
        response = client.post(
            "/api/v1/agents",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"agent_id": "valid_agent-01"},
        )
        assert response.status_code == 200
        assert response.json() == {"agent_id": "valid_agent-01", "status": "stopped"}


class TestPluginMatrix:
    def test_put_matrix_persists_to_agent_config(self, control_app) -> None:
        client, tmp_path = control_app
        client.post(
            "/api/v1/agents",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"agent_id": "matrix_test", "display_name": "矩阵测试"},
        )
        response = client.put(
            "/api/v1/agents/matrix_test/plugins",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"plugins_allow": ["foo", "bar"], "plugins_deny": ["evil"]},
        )
        assert response.status_code == 200
        # 验证 config.jsonc 已更新
        config_file = tmp_path / "agents" / "matrix_test" / "config.jsonc"
        import json

        config = json.loads(config_file.read_text(encoding="utf-8"))
        assert config["plugins_allow"] == ["foo", "bar"]
        assert config["plugins_deny"] == ["evil"]


class TestMetricsInjection:
    """create_control_app(metrics=...) 应使用传入的实例, 而不是内部另建一份

    (CODE_REVIEW_REPORT.md #5: 修复前每次调用都创建独立 Collector, 无法汇聚
    生产链路其他组件记录的指标)。
    """

    def test_injected_metrics_instance_is_reflected_by_endpoints(self, tmp_path: Path) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi 未安装")
        from isac.control.api.server import create_control_app
        from isac.observability import get_default_metrics
        from isac.plugin.runtime.manager import PluginManager
        from isac.router.router import MessageRouter
        from isac.router.types import RoutingRules
        from isac.runtime.bus import InterAgentBus
        from isac.runtime.manager import AgentManager

        metrics = get_default_metrics()
        metrics.counter("isac_messages_received_total").inc(7)

        services = {
            "global_config": {},
            "provider_manager": _StubProviderManager(),
            "memory_factory": lambda namespace: _StubMemory(namespace),
        }
        agent_manager = AgentManager(services)
        router = MessageRouter(RoutingRules(), agents_provider=agent_manager.routing_infos)
        app = create_control_app(
            agent_manager=agent_manager,
            router=router,
            bus=InterAgentBus(),
            plugin_manager=PluginManager({}),
            config={"api_token": "secret-token-123"},
            metrics=metrics,
        )
        client = TestClient(app)

        prom_response = client.get("/metrics")
        assert "isac_messages_received_total 7.0" in prom_response.text

        json_response = client.get(
            "/api/v1/metrics", headers={"Authorization": "Bearer secret-token-123"}
        )
        assert json_response.json()["counters"]["isac_messages_received_total"] == 7.0
