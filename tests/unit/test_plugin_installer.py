"""T6 PluginInstaller 测试: 安装各源 + SSRF/zip slip 防护 + 市场清单。

git/httpx 经 monkeypatch 桩, 不打真实网络/子进程。压缩包用内存 zip 构造。
"""

from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

import pytest

from isac.plugin.runtime.installer import PluginInstaller


def _make_zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _write_zip(path: Path, entries: dict[str, bytes]) -> Path:
    path.write_bytes(_make_zip_bytes(entries))
    return path


class TestInstallUpload:
    @pytest.mark.asyncio
    async def test_install_upload(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        installer = PluginInstaller(plugins_dir=plugins_dir)
        zp = _write_zip(
            tmp_path / "p.zip",
            {"plugin/manifest.jsonc": b'{"name":"x"}', "plugin/plugin.py": b"# stub"},
        )
        result = await installer.install({"type": "upload", "zip_path": str(zp), "name": "myplug"})
        assert result == plugins_dir / "myplug"
        assert (plugins_dir / "myplug" / "manifest.jsonc").exists()

    @pytest.mark.asyncio
    async def test_install_upload_b64(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        installer = PluginInstaller(plugins_dir=plugins_dir)
        data = _make_zip_bytes({"manifest.jsonc": b'{"name":"x"}'})
        await installer.install(
            {"type": "upload", "zip_b64": base64.b64encode(data).decode(), "name": "myplug"}
        )
        assert (plugins_dir / "myplug" / "manifest.jsonc").exists()

    @pytest.mark.asyncio
    async def test_install_failure_rollback(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        installer = PluginInstaller(plugins_dir=plugins_dir)
        zp = _write_zip(tmp_path / "bad.zip", {"readme.txt": b"not a plugin"})
        with pytest.raises(ValueError, match="不是合法插件"):
            await installer.install({"type": "upload", "zip_path": str(zp), "name": "bad"})
        assert not (plugins_dir / "bad").exists()

    @pytest.mark.asyncio
    async def test_install_zip_slip_rejected(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        installer = PluginInstaller(plugins_dir=plugins_dir)
        zp = _write_zip(
            tmp_path / "slip.zip",
            {"../evil.txt": b"x", "manifest.jsonc": b'{"name":"x"}'},
        )
        with pytest.raises(ValueError, match="zip slip"):
            await installer.install({"type": "upload", "zip_path": str(zp), "name": "slip"})
        assert not (tmp_path / "evil.txt").exists()


class TestInstallUrl:
    @pytest.mark.asyncio
    async def test_ssrf_rejected(self, tmp_path: Path) -> None:
        installer = PluginInstaller(plugins_dir=tmp_path / "plugins")
        with pytest.raises(ValueError, match="SSRF"):
            await installer.install({"type": "url", "url": "http://192.168.1.1/x.zip", "name": "x"})

    @pytest.mark.asyncio
    async def test_install_url(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        plugins_dir = tmp_path / "plugins"
        installer = PluginInstaller(plugins_dir=plugins_dir)
        data = _make_zip_bytes({"manifest.jsonc": b'{"name":"x"}'})

        async def fake_download(url: str) -> tuple[Path, Path]:
            dl = tmp_path / "dltmp"
            dl.mkdir()
            zp = dl / "plugin.zip"
            zp.write_bytes(data)
            return zp, dl

        monkeypatch.setattr(installer, "_download_url", fake_download)
        await installer.install({"type": "url", "url": "http://1.1.1.1/x.zip", "name": "myplug"})
        assert (plugins_dir / "myplug" / "manifest.jsonc").exists()


class TestInstallGit:
    @pytest.mark.asyncio
    async def test_install_git(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        plugins_dir = tmp_path / "plugins"
        installer = PluginInstaller(plugins_dir=plugins_dir)

        def fake_run(cmd: list[str], **_kw: object) -> None:
            target = Path(cmd[-1])
            target.mkdir(parents=True, exist_ok=True)
            (target / "manifest.jsonc").write_text('{"name":"x"}')

        monkeypatch.setattr("subprocess.run", fake_run)
        await installer.install(
            {"type": "git", "repo_url": "http://1.1.1.1/x.git", "name": "myplug"}
        )
        assert (plugins_dir / "myplug" / "manifest.jsonc").exists()

    @pytest.mark.asyncio
    async def test_git_unavailable_degrades(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        plugins_dir = tmp_path / "plugins"
        installer = PluginInstaller(plugins_dir=plugins_dir)

        def fake_run(cmd: list[str], **_kw: object) -> None:
            raise FileNotFoundError("git not found")

        monkeypatch.setattr("subprocess.run", fake_run)

        async def fake_install_url(source: dict, name: str) -> Path:
            (plugins_dir / name).mkdir(parents=True, exist_ok=True)
            (plugins_dir / name / "manifest.jsonc").write_text('{"name":"x"}')
            return plugins_dir / name

        monkeypatch.setattr(installer, "_install_url", fake_install_url)
        await installer.install(
            {
                "type": "git",
                "repo_url": "http://1.1.1.1/x.git",
                "name": "myplug",
                "download_url": "http://1.1.1.1/x.zip",
            }
        )
        assert (plugins_dir / "myplug" / "manifest.jsonc").exists()

    @pytest.mark.asyncio
    async def test_git_unavailable_no_download(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        installer = PluginInstaller(plugins_dir=tmp_path / "plugins")

        def fake_run(cmd: list[str], **_kw: object) -> None:
            raise FileNotFoundError("git not found")

        monkeypatch.setattr("subprocess.run", fake_run)
        with pytest.raises(RuntimeError, match="git 未安装"):
            await installer.install(
                {"type": "git", "repo_url": "http://1.1.1.1/x.git", "name": "myplug"}
            )


class TestMarketplace:
    @pytest.mark.asyncio
    async def test_load_local(self, tmp_path: Path) -> None:
        mp = tmp_path / "market.jsonc"
        mp.write_text('{"plugins": [{"name": "a", "version": "1"}]}')
        installer = PluginInstaller(plugins_dir=tmp_path, marketplace_local_path=mp)
        entries = await installer.load_marketplace()
        assert len(entries) == 1
        assert entries[0]["name"] == "a"

    @pytest.mark.asyncio
    async def test_load_remote_merge(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mp = tmp_path / "market.jsonc"
        mp.write_text('{"plugins": [{"name": "a", "version": "1"}]}')
        installer = PluginInstaller(
            plugins_dir=tmp_path,
            marketplace_local_path=mp,
            marketplace_url="http://1.1.1.1/m.json",
        )

        async def fake_fetch(self: PluginInstaller) -> list[dict]:
            return [{"name": "b", "version": "2"}]

        monkeypatch.setattr(PluginInstaller, "_fetch_remote_marketplace", fake_fetch)
        entries = await installer.load_marketplace()
        assert {e["name"] for e in entries} == {"a", "b"}

    @pytest.mark.asyncio
    async def test_remote_failure_degrades(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mp = tmp_path / "market.jsonc"
        mp.write_text('{"plugins": [{"name": "a", "version": "1"}]}')
        installer = PluginInstaller(
            plugins_dir=tmp_path,
            marketplace_local_path=mp,
            marketplace_url="http://1.1.1.1/m.json",
        )

        async def fake_fetch(self: PluginInstaller) -> list[dict]:
            raise RuntimeError("network")

        monkeypatch.setattr(PluginInstaller, "_fetch_remote_marketplace", fake_fetch)
        entries = await installer.load_marketplace()
        assert len(entries) == 1
        assert entries[0]["name"] == "a"


class TestUninstallUpdate:
    @pytest.mark.asyncio
    async def test_uninstall(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        (plugins_dir / "x").mkdir(parents=True)
        (plugins_dir / "x" / "manifest.jsonc").write_text("{}")
        installer = PluginInstaller(plugins_dir=plugins_dir)
        assert await installer.uninstall("x") is True
        assert not (plugins_dir / "x").exists()

    @pytest.mark.asyncio
    async def test_uninstall_nonexistent(self, tmp_path: Path) -> None:
        installer = PluginInstaller(plugins_dir=tmp_path / "plugins")
        assert await installer.uninstall("nope") is False


class TestPluginNameValidation:
    """N5b 批次C C6: 插件名校验 (防路径穿越) + update 原子回滚。"""

    @pytest.mark.asyncio
    async def test_install_rejects_path_traversal_name(self, tmp_path: Path) -> None:
        """name='../evil' 等含穿越字符应拒 (防越界写盘)。"""
        installer = PluginInstaller(plugins_dir=tmp_path / "plugins")
        with pytest.raises(ValueError, match="非法插件名"):
            await installer.install({"type": "upload", "name": "../evil", "zip_path": "x"})

    @pytest.mark.asyncio
    async def test_install_rejects_name_with_slash(self, tmp_path: Path) -> None:
        """name 含路径分隔符应拒。"""
        installer = PluginInstaller(plugins_dir=tmp_path / "plugins")
        with pytest.raises(ValueError, match="非法插件名"):
            await installer.install({"type": "upload", "name": "a/b", "zip_path": "x"})

    @pytest.mark.asyncio
    async def test_update_atomic_rollback_on_failure(self, tmp_path: Path) -> None:
        """update 失败时旧目录应保留 (原子交换回滚, 不再 uninstall+install 丢插件)。"""
        plugins_dir = tmp_path / "plugins"
        installer = PluginInstaller(plugins_dir=plugins_dir)
        # 先装一个可用插件
        zp = _write_zip(
            tmp_path / "p.zip",
            {"plugin/manifest.jsonc": b'{"name":"x"}', "plugin/plugin.py": b"# stub"},
        )
        await installer.install({"type": "upload", "zip_path": str(zp), "name": "myplug"})
        assert (plugins_dir / "myplug").exists()
        # update 用一个无效 source (market 查不到) → 应失败 + 回滚保留旧目录
        with pytest.raises(Exception):
            await installer.update("myplug", source=None)  # market 清单无 myplug
        assert (plugins_dir / "myplug").exists(), "update 失败应回滚保留旧插件目录"
