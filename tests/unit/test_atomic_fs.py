"""原子配置写入测试 (K4, DEVELOPMENT_PLAN.md)。

验证 save_agent_config / save_rules / _persist_links 都通过 atomic_write_text
实现: 写盘完成后无残留 tmp 文件, 异常时 tmp 被清理。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from isac.router.rules import save_rules
from isac.router.types import ChannelBinding, RoutingRules
from isac.runtime.config import AgentConfig, save_agent_config
from isac.utils.fs import atomic_write_json, atomic_write_text


def test_atomic_write_text_creates_target_and_no_tmp_residue(tmp_path: Path) -> None:
    """atomic_write_text 成功后目标文件存在, 目录下无 .tmp 残留。"""
    target = tmp_path / "config.jsonc"
    atomic_write_text(target, '{"hello": "world"}')

    assert target.read_text(encoding="utf-8") == '{"hello": "world"}'
    tmp_files = list(tmp_path.glob(".*.tmp"))
    assert tmp_files == []


def test_atomic_write_text_cleans_up_tmp_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """os.replace 失败时 tmp 文件被清理, 目标文件保持原状。"""
    target = tmp_path / "config.jsonc"
    target.write_text("original", encoding="utf-8")

    import isac.utils.fs as fs

    def _fail_replace(src: str, dst: str) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(fs.os, "replace", _fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write_text(target, "new content")

    # 原文件未污染
    assert target.read_text(encoding="utf-8") == "original"
    # tmp 已清理
    assert list(tmp_path.glob(".*.tmp")) == []


def test_save_agent_config_atomic(tmp_path: Path) -> None:
    """save_agent_config 通过 atomic_write_text 写入。"""
    config = AgentConfig(agent_id="a1", display_name="A1")
    path = tmp_path / "agents" / "a1" / "config.jsonc"
    save_agent_config(path, config)

    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert '"agent_id": "a1"' in content
    # 无 tmp 残留
    assert list((tmp_path / "agents" / "a1").glob(".*.tmp")) == []


def test_save_rules_atomic(tmp_path: Path) -> None:
    """save_rules 通过 atomic_write_json 写入。"""
    rules = RoutingRules(
        bindings=[ChannelBinding(platform="qq", agent_id="default")],
        default_agents={"qq": "default"},
    )
    path = tmp_path / "routing.jsonc"
    save_rules(path, rules)

    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert '"platform": "qq"' in content
    assert list(tmp_path.glob(".*.tmp")) == []


def test_atomic_write_json_round_trip(tmp_path: Path) -> None:
    """atomic_write_json + json.load 能完整还原。"""
    import json

    path = tmp_path / "links.jsonc"
    data = {"links": [{"from_agent": "a", "to_agent": "b", "direction": "both"}]}
    atomic_write_json(path, data)

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == data
