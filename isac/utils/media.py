"""J2 阶段 2: MediaNormalizer — 媒体输入统一校验 (SPECIFICATION.md 2.4)。

把 URI (当前仅支持本地路径) 校验为受控 ``MediaInput``:
- 路径白名单 (默认 data/artifacts/, 可配置多个目录): 拒绝 .. 穿越与越界绝对路径
- MIME 推断 (mimetypes.guess_type): 未知扩展名或非 image|audio|video MIME 拒绝
- 大小上限 (按 kind 配置, 默认 image 25MB / audio 50MB / video 200MB / file 50MB)
- expected_kind 不匹配拒 (例如 STT 工具要求 audio 输入, 收到 image 拒)

URL 输入当前不做 HTTP 下载 (J2 范围内只做出站, 入站留 J3), 直接拒绝。

magic-byte 校验留 TODO (J3+): 当前依赖 mimetypes.guess_type 推断扩展名。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from isac.artifacts.models import MediaInput
from isac.core.exceptions import MediaValidationError
from isac.utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_ALLOWED_DIRS = ("data/artifacts",)
_DEFAULT_SIZE_LIMITS: dict[str, int] = {
    "image": 25 * 1024 * 1024,
    "audio": 50 * 1024 * 1024,
    "video": 200 * 1024 * 1024,
    "file": 50 * 1024 * 1024,
}

# 简化的 magic-byte 签名: 仅用作辅助校验, 不强制 (留 J3+ 完整实现)
# 当前 mimetypes.guess_type 已能从扩展名推断, magic-byte 校验为 TODO。
_MAGIC_BYTES: dict[str, list[bytes]] = {
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "audio/mpeg": [b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xfa"],
    "audio/wav": [b"RIFF"],  # RIFF....WAVE
    "audio/x-wav": [b"RIFF"],
    "video/mp4": [b"ftyp"],  # 偏移 4
}


class MediaNormalizer:
    """把 URI 校验为受控 MediaInput。

    Args:
        config: ``{"allowed_dirs": [str], "size_limits": {kind: int}}``;
            缺省时用 data/artifacts + 默认 size 上限。
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        allowed = cfg.get("allowed_dirs") or list(_DEFAULT_ALLOWED_DIRS)
        self.allowed_dirs: list[Path] = [Path(p).resolve() for p in allowed]
        # 缺省合并: 用户配置覆盖默认 key, 未覆盖的沿用默认
        limits = dict(_DEFAULT_SIZE_LIMITS)
        limits.update(cfg.get("size_limits") or {})
        self.size_limits = limits

    def normalize(self, uri: str, expected_kind: str | None = None) -> MediaInput:
        """把 URI 校验为 MediaInput; 任何校验失败抛 MediaValidationError。"""
        # 1. URL 当前不支持 (J2 不做入站 HTTP 下载)
        if uri.startswith(("http://", "https://")):
            raise MediaValidationError(
                f"URL 输入暂不支持 (需先下载到本地白名单目录): {uri}",
                context={"uri": uri},
            )

        # 2. 路径穿越防护: 显式拒 ..
        raw_path = Path(uri)
        if ".." in raw_path.parts:
            raise MediaValidationError(
                f"路径包含 .. 穿越: {uri}",
                context={"uri": uri},
            )

        # 3. 解析为绝对路径 (相对路径按 cwd 解析, 再 resolve() 去 symlink)
        resolved = raw_path if raw_path.is_absolute() else (Path.cwd() / raw_path)
        resolved = resolved.resolve(strict=False)

        # 4. 白名单校验: 必须落在某个 allowed_dirs 内
        if not self._is_within_whitelist(resolved):
            raise MediaValidationError(
                f"路径不在白名单目录: {uri}",
                context={"uri": uri, "allowed_dirs": [str(p) for p in self.allowed_dirs]},
            )

        # 5. 文件存在性
        if not resolved.exists():
            raise MediaValidationError(
                f"文件不存在: {uri}",
                context={"uri": uri, "resolved": str(resolved)},
            )
        if not resolved.is_file():
            raise MediaValidationError(
                f"不是文件: {uri}",
                context={"uri": uri, "resolved": str(resolved)},
            )

        # 6. MIME 推断 (mimetypes.guess_type)
        mime_type, _ = mimetypes.guess_type(str(resolved))
        if not mime_type:
            raise MediaValidationError(
                f"无法推断 MIME 类型 (未知扩展名): {uri}",
                context={"uri": uri},
            )

        # 7. kind 推断 (image|audio|video; 其他 MIME 拒)
        kind = self._infer_kind(mime_type)
        if not kind:
            raise MediaValidationError(
                f"未知 MIME 类型 (非 image/audio/video): {mime_type}",
                context={"uri": uri, "mime_type": mime_type},
            )

        # 8. expected_kind 校验
        if expected_kind is not None and kind != expected_kind:
            raise MediaValidationError(
                f"期望 {expected_kind} 但实际是 {kind} (mime={mime_type})",
                context={"uri": uri, "expected": expected_kind, "actual": kind},
            )

        # 9. 大小上限
        size = resolved.stat().st_size
        limit = self.size_limits.get(kind, self.size_limits["file"])
        if size > limit:
            raise MediaValidationError(
                f"文件超过 {kind} 上限 ({size} > {limit} bytes)",
                context={"uri": uri, "size": size, "limit": limit, "kind": kind},
            )

        # TODO(J3+): magic-byte 校验 (PNG/JPG/WEBP/MP3/WAV/MP4 头部签名)
        # 当前依赖 mimetypes.guess_type, 扩展名伪造会绕过; 留 J3 完整实现。

        return MediaInput(
            kind=kind,
            uri=str(resolved),
            mime_type=mime_type,
            size_bytes=size,
            source="local",
            metadata={},
        )

    def _is_within_whitelist(self, resolved: Path) -> bool:
        """resolved 必须严格落在某个 allowed_dirs 子树内 (用 is_relative_to)。"""
        return any(resolved.is_relative_to(allowed) for allowed in self.allowed_dirs)

    @staticmethod
    def _infer_kind(mime_type: str) -> str | None:
        if mime_type.startswith("image/"):
            return "image"
        if mime_type.startswith("audio/"):
            return "audio"
        if mime_type.startswith("video/"):
            return "video"
        return None
