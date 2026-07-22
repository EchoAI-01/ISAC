"""I2 Docker 部署测试 - 配置文件正确性。"""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DOCKERFILE = PROJECT_ROOT / "Dockerfile"
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"
DOCKERIGNORE = PROJECT_ROOT / ".dockerignore"
DEPLOY_SCRIPT = PROJECT_ROOT / "scripts" / "docker_deploy.sh"


class TestDockerfile:
    def test_dockerfile_exists(self) -> None:
        assert DOCKERFILE.exists()

    def test_dockerfile_uses_python_312_slim(self) -> None:
        content = DOCKERFILE.read_text(encoding="utf-8")
        assert "FROM python:3.12-slim AS builder" in content
        assert "FROM python:3.12-slim AS runtime" in content

    def test_dockerfile_exposes_control_port(self) -> None:
        content = DOCKERFILE.read_text(encoding="utf-8")
        assert "EXPOSE 8765" in content

    def test_dockerfile_has_healthcheck(self) -> None:
        content = DOCKERFILE.read_text(encoding="utf-8")
        assert "HEALTHCHECK" in content
        assert "/health" in content

    def test_dockerfile_uses_uv_for_dependencies(self) -> None:
        content = DOCKERFILE.read_text(encoding="utf-8")
        assert "uv sync" in content
        assert "--extra onebot" in content

    def test_dockerfile_persists_data_volume(self) -> None:
        content = DOCKERFILE.read_text(encoding="utf-8")
        assert "VOLUME" in content
        assert "/app/data" in content

    def test_dockerfile_entrypoint_runs_isac(self) -> None:
        content = DOCKERFILE.read_text(encoding="utf-8")
        assert 'CMD ["python", "-m", "isac"]' in content


class TestDockerCompose:
    def test_compose_file_exists(self) -> None:
        assert COMPOSE_FILE.exists()

    def test_compose_exposes_control_port_on_localhost(self) -> None:
        content = COMPOSE_FILE.read_text(encoding="utf-8")
        assert "127.0.0.1:8765:8765" in content

    def test_compose_has_data_volume(self) -> None:
        content = COMPOSE_FILE.read_text(encoding="utf-8")
        assert "isac_data:/app/data" in content
        assert "volumes:" in content

    def test_compose_has_restart_policy(self) -> None:
        content = COMPOSE_FILE.read_text(encoding="utf-8")
        assert "restart: unless-stopped" in content

    def test_compose_has_healthcheck(self) -> None:
        content = COMPOSE_FILE.read_text(encoding="utf-8")
        assert "healthcheck:" in content

    def test_compose_has_environment_variables(self) -> None:
        content = COMPOSE_FILE.read_text(encoding="utf-8")
        for var in [
            "ISAC_API_TOKEN",
            "ISAC_LLM_PROVIDER",
            "ISAC_LLM_API_KEY",
            "ISAC_ONEBOT_ENABLED",
        ]:
            assert var in content, f"缺少环境变量 {var}"


class TestDockerignore:
    def test_dockerignore_exists(self) -> None:
        assert DOCKERIGNORE.exists()

    def test_dockerignore_excludes_cache_and_venv(self) -> None:
        content = DOCKERIGNORE.read_text(encoding="utf-8")
        assert "__pycache__/" in content
        assert ".venv/" in content
        assert ".pytest_cache/" in content

    def test_dockerignore_excludes_tests(self) -> None:
        content = DOCKERIGNORE.read_text(encoding="utf-8")
        assert "tests/" in content

    def test_dockerignore_excludes_data_runtime(self) -> None:
        content = DOCKERIGNORE.read_text(encoding="utf-8")
        assert "data/*" in content
        # 保留 .gitkeep 占位
        assert "!data/.gitkeep" in content


class TestDeployScript:
    def test_deploy_script_exists_and_executable(self) -> None:
        assert DEPLOY_SCRIPT.exists()
        # 验证可执行权限
        assert DEPLOY_SCRIPT.stat().st_mode & 0o100

    def test_deploy_script_has_all_commands(self) -> None:
        content = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        for cmd in ["build", "up", "down", "logs", "shell", "health", "restart", "rebuild"]:
            assert cmd in content, f"脚本缺少 {cmd} 命令"

    def test_deploy_script_help_lists_all_commands(self) -> None:
        # 运行 help 命令验证
        result = subprocess.run(
            ["bash", str(DEPLOY_SCRIPT), "help"],
            capture_output=True, text=True, timeout=10,
        )
        assert "ISAC Docker 部署脚本" in result.stdout
        for cmd in ["build", "up", "down", "logs", "shell", "health", "restart", "rebuild"]:
            assert cmd in result.stdout
