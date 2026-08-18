"""J2 阶段 2: MediaNormalizer 单元测试。

覆盖:
- 合法 PNG → MediaInput(kind=image, mime_type=image/png)
- 路径白名单: .. 穿越 / 绝对路径越界 / 自定义白名单目录生效
- 大小上限: 超 25MB 拒
- MIME 推断: 未知扩展名 / 非 image|audio|video MIME 拒
- expected_kind 不匹配拒
- URL 输入拒 (J2 不做入站 HTTP 下载)
- 不存在文件拒
"""

from __future__ import annotations

from pathlib import Path

import pytest

from isac.artifacts.models import MediaInput
from isac.core.exceptions import MediaValidationError
from isac.utils.media import MediaNormalizer


def _write_png(path: Path, size_bytes: int = 100) -> None:
    """写一个最小合法 PNG 文件 (前 8 字节 magic + 填充到 size_bytes)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    png_magic = b"\x89PNG\r\n\x1a\n"
    if size_bytes <= len(png_magic):
        path.write_bytes(png_magic[:size_bytes])
    else:
        path.write_bytes(png_magic + b"\x00" * (size_bytes - len(png_magic)))


def _write_wav(path: Path, size_bytes: int = 100) -> None:
    """写一个最小合法 WAV 头 (RIFF + WAVE)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    wav_magic = b"RIFF" + b"\x00" * 4 + b"WAVE"
    if size_bytes <= len(wav_magic):
        path.write_bytes(wav_magic[:size_bytes])
    else:
        path.write_bytes(wav_magic + b"\x00" * (size_bytes - len(wav_magic)))


@pytest.fixture
def normalizer(tmp_path: Path) -> MediaNormalizer:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    return MediaNormalizer({"allowed_dirs": [str(artifacts_dir)]})


def test_normalize_valid_png(normalizer: MediaNormalizer, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    png_path = artifacts_dir / "test.png"
    _write_png(png_path, size_bytes=100)
    media = normalizer.normalize(str(png_path))
    assert isinstance(media, MediaInput)
    assert media.kind == "image"
    assert media.mime_type == "image/png"
    assert media.size_bytes == 100
    assert media.source == "local"
    assert media.uri.endswith("test.png")


def test_normalize_rejects_forged_extension(normalizer: MediaNormalizer, tmp_path: Path) -> None:
    """magic-byte 校验: 扩展名 .png 但内容非 PNG 头 → 拒 (防扩展名伪造)。"""
    fake = tmp_path / "artifacts" / "evil.png"
    fake.write_bytes(b"<html>not a png</html>")  # 非 PNG magic 头
    with pytest.raises(MediaValidationError, match="签名与"):
        normalizer.normalize(str(fake))


def test_normalize_valid_wav_passes_magic_check(normalizer: MediaNormalizer, tmp_path: Path) -> None:
    """WAV RIFF 头通过 magic-byte 校验 (RIFF@0)。"""
    wav = tmp_path / "artifacts" / "clip.wav"
    _write_wav(wav, size_bytes=100)
    media = normalizer.normalize(str(wav))
    assert media.kind == "audio"
    assert media.mime_type == "audio/x-wav"


def test_normalize_skips_magic_for_unregistered_mime(
    normalizer: MediaNormalizer, tmp_path: Path
) -> None:
    """未登记签名的 MIME (如 image/webp) 跳过 magic 校验, 不引入新拒 (向后兼容)。"""
    webp = tmp_path / "artifacts" / "pic.webp"
    webp.write_bytes(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 80)  # webp 未登记, 跳过校验
    media = normalizer.normalize(str(webp))
    assert media.kind == "image"


def test_normalize_path_traversal_rejected(normalizer: MediaNormalizer, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    png_path = artifacts_dir / "test.png"
    _write_png(png_path)
    # 构造一个含 .. 的路径, 即使最终解析后落在白名单内也必须拒
    traversal = str(artifacts_dir) + "/../artifacts/test.png"
    with pytest.raises(MediaValidationError, match="路径包含"):
        normalizer.normalize(traversal)


def test_normalize_absolute_path_outside_whitelist_rejected(
    normalizer: MediaNormalizer, tmp_path: Path
) -> None:
    outside = tmp_path / "outside" / "evil.png"
    _write_png(outside)
    with pytest.raises(MediaValidationError, match="不在白名单"):
        normalizer.normalize(str(outside))


def test_normalize_relative_path_resolves_to_cwd_rejected(
    normalizer: MediaNormalizer, tmp_path: Path, monkeypatch
) -> None:
    # 相对路径解析后不在白名单内 (cwd 是 tmp_path, 不在 allowed_dirs)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evil.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
    with pytest.raises(MediaValidationError, match="不在白名单"):
        normalizer.normalize("evil.png")


def test_normalize_size_limit_image_rejected(normalizer: MediaNormalizer, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    png_path = artifacts_dir / "huge.png"
    _write_png(png_path, size_bytes=26 * 1024 * 1024)  # 26MB > 25MB image 上限
    with pytest.raises(MediaValidationError, match="超过"):
        normalizer.normalize(str(png_path))


def test_normalize_unknown_extension_rejected(normalizer: MediaNormalizer, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    txt_path = artifacts_dir / "data.txt"
    txt_path.write_text("hello")
    with pytest.raises(MediaValidationError, match="MIME"):
        normalizer.normalize(str(txt_path))


def test_normalize_non_media_mime_rejected(normalizer: MediaNormalizer, tmp_path: Path) -> None:
    # .html 是已知 MIME 但不是 image/audio/video
    artifacts_dir = tmp_path / "artifacts"
    html_path = artifacts_dir / "page.html"
    html_path.write_text("<html></html>")
    with pytest.raises(MediaValidationError, match="未知 MIME|未知类型"):
        normalizer.normalize(str(html_path))


def test_normalize_expected_kind_mismatch_rejected(
    normalizer: MediaNormalizer, tmp_path: Path
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    png_path = artifacts_dir / "img.png"
    _write_png(png_path)
    with pytest.raises(MediaValidationError, match="期望"):
        normalizer.normalize(str(png_path), expected_kind="audio")


def test_normalize_url_rejected(normalizer: MediaNormalizer) -> None:
    with pytest.raises(MediaValidationError, match="URL"):
        normalizer.normalize("https://example.com/image.png")


def test_normalize_nonexistent_file_rejected(normalizer: MediaNormalizer, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    with pytest.raises(MediaValidationError, match="不存在"):
        normalizer.normalize(str(artifacts_dir / "missing.png"))


def test_normalize_custom_whitelist_dir(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    png_path = uploads / "user.png"
    _write_png(png_path)
    normalizer = MediaNormalizer({"allowed_dirs": [str(uploads)]})
    media = normalizer.normalize(str(png_path))
    assert media.kind == "image"


def test_normalize_wav_recognized_as_audio(normalizer: MediaNormalizer, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    wav_path = artifacts_dir / "voice.wav"
    _write_wav(wav_path, size_bytes=200)
    media = normalizer.normalize(str(wav_path))
    assert media.kind == "audio"
    # 不同平台 mimetypes 可能返回 audio/wav 或 audio/x-wav, 都接受
    assert media.mime_type.startswith("audio/")


def test_normalize_expected_kind_matches_passes(
    normalizer: MediaNormalizer, tmp_path: Path
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    png_path = artifacts_dir / "img.png"
    _write_png(png_path)
    media = normalizer.normalize(str(png_path), expected_kind="image")
    assert media.kind == "image"
