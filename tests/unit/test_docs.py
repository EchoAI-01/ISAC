"""I3 文档完善测试 - 验证 5 篇文档存在 + 完整性。"""

from __future__ import annotations

from pathlib import Path

import pytest

DOCS_DIR = Path(__file__).parent.parent.parent / "docs"

REQUIRED_DOCS = [
    "README.md",
    "usage.md",
    "deployment.md",
    "api.md",
    "plugin_development.md",
    "control_automation.md",
]


@pytest.mark.parametrize("doc_name", REQUIRED_DOCS)
def test_required_doc_exists(doc_name: str) -> None:
    assert (DOCS_DIR / doc_name).exists(), f"文档 {doc_name} 不存在"


class TestUsageDoc:
    def test_usage_doc_contains_quick_start(self) -> None:
        content = (DOCS_DIR / "usage.md").read_text(encoding="utf-8")
        assert "快速开始" in content
        assert "uv sync" in content

    def test_usage_doc_contains_config_examples(self) -> None:
        content = (DOCS_DIR / "usage.md").read_text(encoding="utf-8")
        assert "config.jsonc" in content
        assert "llm" in content
        assert "channels" in content

    def test_usage_doc_contains_maintenance(self) -> None:
        content = (DOCS_DIR / "usage.md").read_text(encoding="utf-8")
        assert "维护与排错" in content
        assert "审计日志" in content


class TestDeploymentDoc:
    def test_deployment_doc_contains_dockerfile_section(self) -> None:
        content = (DOCS_DIR / "deployment.md").read_text(encoding="utf-8")
        assert "镜像构建" in content
        assert "Dockerfile" in content

    def test_deployment_doc_contains_env_vars(self) -> None:
        content = (DOCS_DIR / "deployment.md").read_text(encoding="utf-8")
        assert "ISAC_API_TOKEN" in content
        assert "ISAC_LLM_API_KEY" in content

    def test_deployment_doc_contains_production_advice(self) -> None:
        content = (DOCS_DIR / "deployment.md").read_text(encoding="utf-8")
        assert "生产部署建议" in content
        assert "nginx" in content


class TestAPIDoc:
    def test_api_doc_contains_all_endpoints(self) -> None:
        content = (DOCS_DIR / "api.md").read_text(encoding="utf-8")
        for endpoint in ["/agents", "/routing/rules", "/links", "/plugins", "/audit", "/health"]:
            assert endpoint in content

    def test_api_doc_contains_auth_section(self) -> None:
        content = (DOCS_DIR / "api.md").read_text(encoding="utf-8")
        assert "Bearer" in content
        assert "认证" in content

    def test_api_doc_contains_error_codes(self) -> None:
        content = (DOCS_DIR / "api.md").read_text(encoding="utf-8")
        assert "AGENT_NOT_FOUND" in content
        assert "401" in content


class TestPluginDevDoc:
    def test_plugin_doc_covers_three_formats(self) -> None:
        content = (DOCS_DIR / "plugin_development.md").read_text(encoding="utf-8")
        assert "ISAC 原生" in content
        assert "AstrBot 兼容" in content
        assert "MaiBot 兼容" in content

    def test_plugin_doc_has_manifest_example(self) -> None:
        content = (DOCS_DIR / "plugin_development.md").read_text(encoding="utf-8")
        assert "manifest.jsonc" in content
        assert "isac_version" in content

    def test_plugin_doc_has_lifecycle_section(self) -> None:
        content = (DOCS_DIR / "plugin_development.md").read_text(encoding="utf-8")
        assert "on_load" in content
        assert "on_unload" in content


class TestControlAutomationDoc:
    def test_control_doc_covers_three_entry_points(self) -> None:
        content = (DOCS_DIR / "control_automation.md").read_text(encoding="utf-8")
        assert "Admin REST API" in content
        assert "MCP Server" in content
        assert "Webhooks" in content

    def test_control_doc_has_mcp_tool_list(self) -> None:
        content = (DOCS_DIR / "control_automation.md").read_text(encoding="utf-8")
        assert "agent_create" in content
        assert "link_create" in content
        assert "message_send" in content

    def test_control_doc_has_security_section(self) -> None:
        content = (DOCS_DIR / "control_automation.md").read_text(encoding="utf-8")
        assert "安全" in content
        assert "Bearer" in content


class TestDocsReadmeIndex:
    def test_docs_readme_lists_all_docs(self) -> None:
        content = (DOCS_DIR / "README.md").read_text(encoding="utf-8")
        for doc in REQUIRED_DOCS:
            if doc == "README.md":
                continue
            assert doc in content
