"""I1 WebUI 管理面板测试 - 静态托管 + API 集成。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def webui_client(tmp_path: Path):
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
        config={"api_token": "ui-token"},
    )
    return TestClient(app)


class TestWebUIStatic:
    def test_index_html_returns_200(self, webui_client) -> None:
        response = webui_client.get("/ui/")
        assert response.status_code == 200
        assert "ISAC 管理面板" in response.text
        assert "<table" in response.text

    def test_app_js_returns_200(self, webui_client) -> None:
        response = webui_client.get("/ui/app.js")
        assert response.status_code == 200
        assert "apiCall" in response.text
        assert "Bearer" in response.text

    def test_python_package_files_are_not_served_as_static_assets(self, webui_client) -> None:
        response = webui_client.get("/ui/__init__.py")
        assert response.status_code == 404

    def test_index_contains_all_sections(self, webui_client) -> None:
        response = webui_client.get("/ui/")
        # J3-5: v1 四 section 保留向后兼容
        assert "Agent 管理" in response.text
        assert "路由规则" in response.text
        assert "互联 Link" in response.text
        assert "审计日志" in response.text

    def test_index_contains_j3_spa_sidebar(self, webui_client) -> None:
        """J3-5: 新增 10 域侧边栏导航。"""
        response = webui_client.get("/ui/")
        assert "Dashboard" in response.text
        assert "Channels" in response.text
        assert "Providers" in response.text
        assert "Usage" in response.text
        assert "Extensions" in response.text
        assert "Memory" in response.text
        assert "Sessions" in response.text
        assert "Logs" in response.text
        assert "System" in response.text
        # 侧边栏导航 data-page 属性
        assert 'data-page="dashboard"' in response.text
        assert 'data-page="agents"' in response.text
        assert 'data-page="channels"' in response.text

    def test_app_js_contains_navigate_function(self, webui_client) -> None:
        """J3-5: app.js 含 navigate() + refreshDashboard() 函数。"""
        response = webui_client.get("/ui/app.js")
        assert "function navigate(" in response.text
        assert "function refreshDashboard(" in response.text
        assert "refreshDashboard()" in response.text  # 在 refreshAll 里调用

    def test_index_contains_j3_6_providers_usage_extensions_pages(self, webui_client) -> None:
        """J3-6: Providers / Usage / Extensions 三页真实内容 (非占位)。"""
        response = webui_client.get("/ui/")
        # Providers 页
        assert "已注册 Provider" in response.text
        assert "模型能力目录" in response.text
        assert "制品存储" in response.text
        assert 'id="providers-table"' in response.text
        assert 'id="models-table"' in response.text
        assert 'id="artifacts-table"' in response.text
        # Usage 页
        assert "用量汇总" in response.text
        assert "用量明细" in response.text
        assert 'id="usage-summary-table"' in response.text
        assert 'id="usage-events-table"' in response.text
        # Extensions 页
        assert "插件" in response.text
        assert "SubAgent 任务" in response.text
        assert 'id="subagent-runs-table"' in response.text

    def test_app_js_contains_j3_6_refresh_functions(self, webui_client) -> None:
        """J3-6: app.js 含 refreshProviders/refreshUsage/refreshExtensions。"""
        response = webui_client.get("/ui/app.js")
        assert "function refreshProviders(" in response.text
        assert "function refreshUsage(" in response.text
        assert "function refreshExtensions(" in response.text
        # navigate 里调用了这三页
        assert 'refreshProviders()' in response.text
        assert 'refreshUsage()' in response.text
        assert 'refreshExtensions()' in response.text

    def test_index_contains_j3_7_memory_sessions_system_pages(self, webui_client) -> None:
        """J3-7: Memory / Sessions / System 三页真实内容 + 配置编辑事务 UI。"""
        response = webui_client.get("/ui/")
        # Memory 页
        assert "记忆命名空间" in response.text
        assert "Episode" in response.text
        assert "人物画像" in response.text
        assert "术语" in response.text
        assert 'id="memory-episodes-table"' in response.text
        assert 'id="memory-profiles-table"' in response.text
        assert 'id="memory-jargon-table"' in response.text
        # Sessions 页
        assert "活跃会话" in response.text
        assert "会话消息历史" in response.text
        assert 'id="sessions-table"' in response.text
        assert 'id="session-messages-table"' in response.text
        # System 页
        assert "系统信息" in response.text
        assert "配置编辑事务" in response.text
        assert "Schema 校验" in response.text
        assert "Diff 预览" in response.text
        assert "PATCH 提交" in response.text
        assert 'id="config-revision"' in response.text
        assert 'id="config-diff-output"' in response.text

    def test_app_js_contains_j3_7_functions(self, webui_client) -> None:
        """J3-7: app.js 含 refreshMemory/refreshSessions/refreshSystem + 配置编辑事务。"""
        response = webui_client.get("/ui/app.js")
        assert "function refreshMemory(" in response.text
        assert "function refreshSessions(" in response.text
        assert "function refreshSessionMessages(" in response.text
        assert "function refreshSystem(" in response.text
        # 配置编辑事务
        assert "function loadConfigForEdit(" in response.text
        assert "function validateConfig(" in response.text
        assert "function diffConfig(" in response.text
        assert "function patchConfig(" in response.text
        # navigate 里调用了这三页
        assert 'refreshMemory()' in response.text
        assert 'refreshSessions()' in response.text
        assert 'refreshSystem()' in response.text

    def test_webui_does_not_require_token(self, webui_client) -> None:
        # WebUI 静态资源不需要 token (前端自己带 token 调 API)
        response = webui_client.get("/ui/")
        assert response.status_code == 200

    def test_app_js_does_not_render_audit_fields_via_innerhtml(self, webui_client) -> None:
        """Fix-16: 审计日志的 action/target 字段来自用户可控输入 (如
        InterAgentLink 的 from_agent/to_agent), 之前用 innerHTML 模板字符串拼接
        渲染 (tr.innerHTML = 反引号模板字符串), 一个含 <script> 的值会在
        Dashboard 渲染时被执行, 构成存储型 XSS。修复后必须改用 addRow() (内部用
        textContent 逐格赋值), 不再对审计字段调用 innerHTML。

        本项目未预装可用的 Playwright Chromium 二进制 (playwright install 缺失,
        是既有的环境缺口, 非本次修复范围), 无法在真实浏览器里执行 app.js 验证
        DOM 输出; 这里改用静态源码断言锁定"不再对不可信字段用 innerHTML 拼接"
        这一具体回归点, 由 isac/runtime/bus.py 的 InterAgentLink 格式校验
        (tests/unit/test_interagent_link_validation.py) 提供纵深防御的第二层。
        """
        response = webui_client.get("/ui/app.js")
        js = response.text
        assert "tr.innerHTML = `<td>${ts}</td>" not in js
        assert "addRow(\"dashboard-audit-table\", [ts, e.action" in js


class TestWebUIIntegrationWithAPI:
    def test_full_workflow_via_api(self, webui_client) -> None:
        # 通过 API 模拟 WebUI 的完整工作流
        headers = {"Authorization": "Bearer ui-token"}

        # 1. 创建 Agent
        r = webui_client.post("/api/v1/agents", headers=headers, json={"agent_id": "w1", "display_name": "W1"})
        assert r.status_code == 200

        # 2. 启动 Agent
        r = webui_client.post("/api/v1/agents/w1/start", headers=headers)
        assert r.status_code == 200
        assert r.json()["status"] == "running"

        # 3. 列出 Agent (WebUI /agents endpoint)
        r = webui_client.get("/api/v1/agents", headers=headers)
        assert r.status_code == 200
        assert len(r.json()) >= 1
        assert any(a["agent_id"] == "w1" for a in r.json())

        # 4. 添加 Link
        r = webui_client.post("/api/v1/links", headers=headers, json={
            "from_agent": "w1", "to_agent": "w2", "direction": "both"
        })
        assert r.status_code == 200

        # 5. 查询审计
        r = webui_client.get("/api/v1/audit?limit=10", headers=headers)
        assert r.status_code == 200
        entries = r.json()
        assert len(entries) >= 2  # create_agent + add_link
