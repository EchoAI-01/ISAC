"""R3: CLI 工具后端 services 注入自检 (DEVELOPMENT_PLAN.md §四 R3 第 4 点)。

bash/read_file/write_file 三工具此前因 build_services 未注入 workspace_root/
bash_allowlist 恒被拒 (即使 tools_policy allow 也调不通)。本测试验证 build_services
注入这两个后端 + workspace 目录存在。
"""
from __future__ import annotations

from pathlib import Path


def test_build_services_injects_cli_tool_backends(tmp_path: Path, monkeypatch) -> None:
    """build_services 注入 workspace_root (data/workspace, mkdir) + bash_allowlist。"""
    monkeypatch.setattr("isac.main.DATA_DIR", tmp_path)
    from isac.main import build_services

    services = build_services(
        {"llm": {}, "memory": {"enabled": False}, "tools": {"bash_allowlist": ["ls", "cat"]}}
    )
    assert "workspace_root" in services
    assert services["workspace_root"] == str(tmp_path / "workspace")
    assert Path(services["workspace_root"]).is_dir()  # mkdir 确保存在
    assert services["bash_allowlist"] == ["ls", "cat"]


def test_build_services_default_bash_allowlist_empty(tmp_path: Path, monkeypatch) -> None:
    """未配置 tools.bash_allowlist 时默认空 (禁止所有命令, 但 services 已注入)。"""
    monkeypatch.setattr("isac.main.DATA_DIR", tmp_path)
    from isac.main import build_services

    services = build_services({})
    assert services["bash_allowlist"] == []
    assert services["workspace_root"] == str(tmp_path / "workspace")
    assert Path(services["workspace_root"]).is_dir()
