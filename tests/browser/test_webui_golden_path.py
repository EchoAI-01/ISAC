"""J3 阶段 8: Playwright 浏览器黄金路径测试。

两条黄金路径:
1. 登录 → Agent CRUD (创建/启动/列表/删除) → 审计查询
2. 登录 → 路由规则更新 → 互联 Link 添加 → 用量查询

未安装 Playwright 时整个文件 skip (CI 在 K8-2 加 playwright install chromium step)。
"""

from __future__ import annotations

from typing import Any

import pytest

# 未安装 Playwright 时跳过全部测试
pytest.importorskip(
    "playwright",
    reason="playwright 未安装: pip install pytest-playwright && playwright install chromium",
)
from playwright.sync_api import Page, sync_playwright  # noqa: E402


def _start_test_server() -> tuple[Any, str]:
    """启动测试用 control plane + WebUI, 返回 (server_thread, base_url)。"""
    import socket
    import threading

    import uvicorn

    from isac.control.api.server import create_control_app
    from isac.observability import get_default_metrics
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
        agent_manager=agent_manager, router=router, bus=bus,
        plugin_manager=plugin_manager, config={"api_token": "e2e-token"},
        metrics=get_default_metrics(),
    )
    # 用 uvicorn 启动到随机端口
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # 等待服务器就绪
    import time

    for _ in range(30):
        if server.started:
            break
        time.sleep(0.1)
    return thread, f"http://127.0.0.1:{port}"


@pytest.fixture(scope="module")
def test_server():
    """启动测试服务器, 模块级 fixture (所有测试共享)。"""
    thread, base_url = _start_test_server()
    yield base_url
    # 模块结束时 thread 是 daemon, 自动退出


@pytest.fixture
def browser_page(test_server: str):
    """打开浏览器页面, 走真实登录流程 (Fix-17: /auth/session 换会话 Cookie), 返回 Page。"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"{test_server}/ui/")
        page.fill("#api-token", "e2e-token")
        page.click('button:has-text("登录")')
        page.wait_for_selector(".toast", timeout=2000)
        yield page
        browser.close()


def test_golden_path_agent_crud(browser_page: Page, test_server: str) -> None:
    """黄金路径 1: 登录 → 创建 Agent → 列表 → 启动 → 删除 → 审计查询。"""
    page = browser_page
    # 导航到 Agents 页
    page.click('a[data-page="agents"]')
    # 创建 Agent
    page.fill("#new-agent-id", "e2e-agent")
    page.fill("#new-agent-name", "E2E Agent")
    page.click('button:has-text("创建 Agent")')
    # 验证 toast
    page.wait_for_selector(".toast", timeout=2000)
    # 验证 agent 出现在列表
    page.wait_for_selector("#agents-table td:has-text('e2e-agent')", timeout=2000)
    # 启动 Agent
    page.click('#agents-table tr:has-text("e2e-agent") button:has-text("启动")')
    page.wait_for_selector("#agents-table td:has-text('running')", timeout=2000)
    # 删除 Agent
    page.click('#agents-table tr:has-text("e2e-agent") button:has-text("删除")')
    page.on("dialog", lambda dialog: dialog.accept())  # 自动确认删除
    # 导航到 Logs 页, 验证审计记录
    page.click('a[data-page="logs"]')
    page.wait_for_selector("#audit-table td", timeout=2000)
    audit_text = page.inner_text("#audit-table")
    assert "create_agent" in audit_text


def test_golden_path_routing_and_links(browser_page: Page, test_server: str) -> None:
    """黄金路径 2: 登录 → 路由规则更新 → 互联 Link 添加 → 用量查询。"""
    page = browser_page
    # 导航到 Channels 页
    page.click('a[data-page="channels"]')
    # 更新路由规则
    page.fill("#new-binding-platform", "qq")
    page.fill("#new-binding-agent", "default")
    page.click('button:has-text("更新规则")')
    page.wait_for_selector(".toast", timeout=2000)
    # 添加 Link
    page.fill("#new-link-from", "agent-a")
    page.fill("#new-link-to", "agent-b")
    page.click('button:has-text("添加 Link")')
    page.wait_for_selector(".toast", timeout=2000)
    # 导航到 Usage 页 (无 usage_store 时表格为空, 但不报错)
    page.click('a[data-page="usage"]')
    page.click('button:has-text("查询")')
    # 验证表格存在 (即使空)
    page.wait_for_selector("#usage-summary-table td", timeout=2000)
