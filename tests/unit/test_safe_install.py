"""T6 安装安全原语测试 (isac.utils.safe_install)。

SSRF 校验 + zip slip 防护 + 压缩包入口校验。公网/内网判定用 IP 字面量作 hostname
(避免 DNS 不稳定); localhost 走 hostname 短路分支。
"""

from __future__ import annotations

import io
import zipfile

import pytest

from isac.utils.safe_install import (
    is_safe_url,
    resolve_archive_root_dir,
    safe_extractall,
    validate_plugin_archive,
)


class TestIsSafeUrl:
    def test_rejects_empty(self) -> None:
        assert is_safe_url("") is False

    def test_rejects_non_http_scheme(self) -> None:
        assert is_safe_url("file:///etc/passwd") is False
        assert is_safe_url("ftp://1.1.1.1/x") is False

    def test_rejects_private_ip(self) -> None:
        assert is_safe_url("http://192.168.1.1/x") is False
        assert is_safe_url("http://10.0.0.1/x") is False
        assert is_safe_url("http://172.16.0.1/x") is False

    def test_rejects_loopback(self) -> None:
        assert is_safe_url("http://127.0.0.1/x") is False

    def test_loopback_allowed_with_flag(self) -> None:
        assert is_safe_url("http://127.0.0.1/x", allow_loopback=True) is True

    def test_localhost(self) -> None:
        assert is_safe_url("http://localhost/x") is False
        assert is_safe_url("http://localhost/x", allow_loopback=True) is True

    def test_accepts_public_ip(self) -> None:
        assert is_safe_url("http://1.1.1.1/x") is True

    def test_rejects_no_hostname(self) -> None:
        assert is_safe_url("http:///path") is False


def _make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestSafeExtractall:
    def test_extracts_valid(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[assignment]
        data = _make_zip({"plugin/manifest.jsonc": b"{}", "plugin/plugin.py": b"x"})
        target = tmp / "out"
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            safe_extractall(zf, target)
        assert (target / "plugin" / "manifest.jsonc").exists()
        assert (target / "plugin" / "plugin.py").exists()

    def test_rejects_zip_slip(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[assignment]
        data = _make_zip({"../evil.txt": b"pwned"})
        target = tmp / "out"
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            with pytest.raises(ValueError, match="zip slip"):
                safe_extractall(zf, target)
        assert not (tmp / "evil.txt").exists()

    def test_rejects_absolute_path(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[assignment]
        data = _make_zip({"/etc/evil.txt": b"x"})
        target = tmp / "out"
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            with pytest.raises(ValueError):
                safe_extractall(zf, target)


class TestResolveArchiveRootDir:
    def test_single_subdir(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[assignment]
        sub = tmp / "plugin_pkg"
        sub.mkdir()
        (sub / "manifest.jsonc").write_text("{}")
        assert resolve_archive_root_dir(tmp) == sub

    def test_multiple_files(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[assignment]
        (tmp / "a.txt").write_text("x")
        (tmp / "b.txt").write_text("y")
        assert resolve_archive_root_dir(tmp) == tmp

    def test_ignores_hidden(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[assignment]
        sub = tmp / "real"
        sub.mkdir()
        (tmp / ".hidden").write_text("x")
        assert resolve_archive_root_dir(tmp) == sub


class TestValidatePluginArchive:
    def test_accepts_manifest_jsonc(self) -> None:
        data = _make_zip({"plugin/manifest.jsonc": b'{"name":"x"}'})
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            validate_plugin_archive(zf)  # 不 raise

    def test_accepts_metadata_yaml(self) -> None:
        data = _make_zip({"metadata.yaml": b"name: x"})
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            validate_plugin_archive(zf)

    def test_accepts_mai_plugin_yaml(self) -> None:
        data = _make_zip({"mai_plugin.yaml": b"name: x"})
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            validate_plugin_archive(zf)

    def test_rejects_no_entry(self) -> None:
        data = _make_zip({"readme.txt": b"not a plugin"})
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            with pytest.raises(ValueError, match="不是合法插件"):
                validate_plugin_archive(zf)
