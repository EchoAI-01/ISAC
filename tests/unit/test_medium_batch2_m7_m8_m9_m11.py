"""2026-08-19 Medium 批清第二批回归 (M7/M8/M9/M11)。

覆盖:
- M7  git 安装路径对齐 zip 防护 (入口特征 + symlink 拒绝 + 体积上限)
- M8  loader manifest entry 路径穿越防护 (resolve + is_relative_to)
- M9  CommandRegistry 同名覆盖留痕 (来源追踪不被静默顶替)
- M11 rlimits 默认值可用 + 失败不静默 (不 raise 但留痕)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from isac.commands.base import Command
from isac.commands.registry import CommandRegistry
from isac.plugin.isolation.host import _apply_rlimits
from isac.plugin.runtime.installer import _validate_git_checkout
from isac.plugin.runtime.loader import PluginLoader

# ── M7: git checkout 对齐防护 ─────────────────────────────────


def test_m7_validate_git_checkout_rejects_missing_entry(tmp_path: Path) -> None:
    d = tmp_path / "repo"
    d.mkdir()
    (d / "readme.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="入口特征"):
        _validate_git_checkout(d, 1024 * 1024)


def test_m7_validate_git_checkout_rejects_symlink(tmp_path: Path) -> None:
    d = tmp_path / "repo"
    d.mkdir()
    (d / "manifest.jsonc").write_text("{}", encoding="utf-8")
    target = d / "real.txt"
    target.write_text("x", encoding="utf-8")
    (d / "link").symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        _validate_git_checkout(d, 1024 * 1024)


def test_m7_validate_git_checkout_enforces_size_cap(tmp_path: Path) -> None:
    d = tmp_path / "repo"
    d.mkdir()
    (d / "manifest.jsonc").write_text("{}" * 100, encoding="utf-8")
    with pytest.raises(ValueError, match="体积上限"):
        _validate_git_checkout(d, max_bytes=10)


def test_m7_validate_git_checkout_accepts_valid(tmp_path: Path) -> None:
    d = tmp_path / "repo"
    d.mkdir()
    (d / "manifest.jsonc").write_text("{}", encoding="utf-8")
    (d / "plugin.py").write_text("pass", encoding="utf-8")
    _validate_git_checkout(d, 1024 * 1024)  # 不抛异常即通过


# ── M8: loader entry 路径穿越 ─────────────────────────────────


async def test_m8_loader_entry_dotdot_traversal_rejected(tmp_path: Path) -> None:
    loader = PluginLoader()
    plugin_dir = tmp_path / "p1"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.jsonc").write_text(
        '{"name": "p1", "entry": "../../evil.py"}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="越出插件目录"):
        await loader._load_native(plugin_dir)  # noqa: SLF001


async def test_m8_loader_entry_absolute_path_rejected(tmp_path: Path) -> None:
    loader = PluginLoader()
    plugin_dir = tmp_path / "p1"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.jsonc").write_text(
        '{"name": "p1", "entry": "/etc/passwd"}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="越出插件目录"):
        await loader._load_native(plugin_dir)  # noqa: SLF001


async def test_m8_loader_entry_within_dir_passes_path_check(tmp_path: Path) -> None:
    """合法 entry (目录内) 不被路径校验拦截 —— 推进到后续 exists 检查 (此处文件缺失)。"""
    loader = PluginLoader()
    plugin_dir = tmp_path / "p1"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.jsonc").write_text(
        '{"name": "p1", "entry": "plugin.py"}', encoding="utf-8"
    )
    # plugin.py 不存在 → FileNotFoundError (而非 ValueError), 证明路径校验放行
    with pytest.raises(FileNotFoundError):
        await loader._load_native(plugin_dir)  # noqa: SLF001


# ── M9: CommandRegistry 覆盖留痕 ──────────────────────────────


class _StubCommand(Command):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, message, args: str, context) -> str:  # type: ignore[override]
        return self._name


def test_m9_command_register_conflict_overwrites_and_tracks_source() -> None:
    reg = CommandRegistry()
    reg.register(_StubCommand("mute"), source="builtin")
    # 插件同名命令覆盖: 行为仍覆盖 (不引入命名空间), 但来源追踪必须更新且可观测
    reg.register(_StubCommand("mute"), source="plugin_x")
    assert reg._source["mute"] == "plugin_x"  # noqa: SLF001
    assert reg._commands["mute"].name == "mute"  # noqa: SLF001
    # deregister_by_source 能按新来源清理
    removed = reg.deregister_by_source("plugin_x")
    assert removed == ["mute"]


def test_m9_command_register_no_conflict_no_overwrite_path() -> None:
    reg = CommandRegistry()
    reg.register(_StubCommand("focus"), source="builtin")
    assert reg._source["focus"] == "builtin"  # noqa: SLF001


# ── M11: rlimits 默认值 + 失败不静默 ──────────────────────────


def test_m11_rlimits_failure_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """M11: setrlimit 失败时不 raise (避免平台差异阻断), 但不再静默 (记日志)。"""
    import sys

    if sys.platform == "win32":
        pytest.skip("Windows 无 resource 模块")
    import resource as _r

    def _raise(which: int, limits: tuple[int, int]) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(_r, "setrlimit", _raise)
    # 必须不抛异常 (fail-soft), 仅留痕
    _apply_rlimits(None)


def test_m11_default_cpu_is_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    """M11: 默认 cpu 由不可用的 (1,1) 提到 (60,60), 对齐 sample。"""
    import sys

    if sys.platform == "win32":
        pytest.skip("Windows 无 resource 模块")
    import resource as _r

    calls: dict = {}
    monkeypatch.setattr(_r, "setrlimit", lambda which, limits: calls.__setitem__(which, limits))
    _apply_rlimits(None)
    assert calls.get(_r.RLIMIT_CPU) == (60, 60)
