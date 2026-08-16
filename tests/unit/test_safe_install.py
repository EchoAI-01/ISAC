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


# ── safe_download_bytes (Fix-39): 重定向逐跳 SSRF 复校验 + 流式体积上限 ──


class _FakeStreamResponse:
    """模拟 httpx stream 响应 (status/headers/chunks)。"""

    def __init__(self, status_code: int, headers: dict[str, str] | None = None,
                 chunks: list[bytes] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or []

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk

    async def __aenter__(self) -> _FakeStreamResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakeAsyncClient:
    """按 URL 路由响应的假 AsyncClient (替换 httpx.AsyncClient)。"""

    routes: dict[str, _FakeStreamResponse] = {}

    def __init__(self, timeout: float = 30.0, follow_redirects: bool = False) -> None:
        # Fix-39 的实现必须不自动跟随重定向 (逐跳手动校验)
        assert follow_redirects is False

    def stream(self, method: str, url: str) -> _FakeStreamResponse:
        resp = self.routes.get(url)
        assert resp is not None, f"未预期的请求 URL: {url}"
        return resp

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


@pytest.fixture()
def fake_httpx(monkeypatch: pytest.MonkeyPatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.routes = {}
    return _FakeAsyncClient


class TestSafeDownloadBytes:
    @pytest.mark.asyncio
    async def test_redirect_to_private_ip_rejected(self, fake_httpx) -> None:
        """Fix-39 核心: 初始 URL 安全, 302 重定向到云元数据地址必须被拒。"""
        from isac.utils.safe_install import safe_download_bytes

        fake_httpx.routes = {
            "https://93.184.216.34/a.png": _FakeStreamResponse(
                302, {"location": "http://169.254.169.254/latest/meta-data/"}
            ),
        }
        with pytest.raises(ValueError, match="SSRF"):
            await safe_download_bytes("https://93.184.216.34/a.png")

    @pytest.mark.asyncio
    async def test_redirect_to_safe_target_followed(self, fake_httpx) -> None:
        from isac.utils.safe_install import safe_download_bytes

        fake_httpx.routes = {
            "https://93.184.216.34/a.png": _FakeStreamResponse(
                302, {"location": "https://93.184.216.34/final.png"}
            ),
            "https://93.184.216.34/final.png": _FakeStreamResponse(200, chunks=[b"PNGDATA"]),
        }
        got = await safe_download_bytes("https://93.184.216.34/a.png")
        assert got == b"PNGDATA"

    @pytest.mark.asyncio
    async def test_size_limit_aborts(self, fake_httpx) -> None:
        from isac.utils.safe_install import safe_download_bytes

        fake_httpx.routes = {
            "https://93.184.216.34/big.bin": _FakeStreamResponse(
                200, chunks=[b"x" * 100, b"y" * 100]
            ),
        }
        with pytest.raises(ValueError, match="大小上限"):
            await safe_download_bytes("https://93.184.216.34/big.bin", max_bytes=150)

    @pytest.mark.asyncio
    async def test_redirect_loop_capped(self, fake_httpx) -> None:
        from isac.utils.safe_install import safe_download_bytes

        fake_httpx.routes = {
            "https://93.184.216.34/loop": _FakeStreamResponse(
                302, {"location": "https://93.184.216.34/loop"}
            ),
        }
        with pytest.raises(ValueError, match="重定向"):
            await safe_download_bytes("https://93.184.216.34/loop", max_redirects=2)

    @pytest.mark.asyncio
    async def test_initial_unsafe_url_rejected(self, fake_httpx) -> None:
        from isac.utils.safe_install import safe_download_bytes

        with pytest.raises(ValueError, match="SSRF"):
            await safe_download_bytes("http://127.0.0.1:8765/api/v1/agents")
