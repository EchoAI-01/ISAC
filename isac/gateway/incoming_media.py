"""R1-② 入站媒体下载落盘闭环。

Channel 适配器收消息后, 入站媒体以 MessageSegment 进 ``incoming.segments``
(OneBot CQ image→type="image" data 含 url/file, record→type="voice" 等)。此前
ISACMessage 无 attachments 字段, MediaNormalizer 显式拒绝 URL 输入, 入站媒体
无法被工具使用。

本模块: 扫 segments 中 media 类型, 取 data["url"], HTTP 下载为 bytes →
``ArtifactStore(root_dir="data/uploads").put(...)`` 落盘 → 回填 segment
``data["media_uri"]`` (供工具经 MediaNormalizer 读, 白名单含 data/uploads)。

安全: SSRF 校验 (复用 isac.utils.safe_install.is_safe_url / safe_download_bytes,
后者对重定向逐跳复校验 + 流式体积上限, Fix-39) + 异常隔离 (单个 segment
失败不阻塞消息)。无 url 的 segment (如本地 file 路径) 跳过。
"""

from __future__ import annotations

from typing import Any

from isac.utils.logger import get_logger
from isac.utils.safe_install import is_safe_url, safe_download_bytes

logger = get_logger(__name__)

# 入站媒体单文件体积上限 (防超大响应 OOM; 与 MediaNormalizer 的 image 25MB 上限同量级)
MAX_INBOUND_MEDIA_BYTES = 50 * 1024 * 1024

# 入站 segment type → ArtifactStore kind 映射
_SEGMENT_KIND: dict[str, str] = {
    "image": "image",
    "voice": "audio",
    "audio": "audio",
    "video": "video",
    "file": "file",
}


async def download_inbound_media(
    message: Any,
    artifact_store: Any,
    *,
    http_client: Any = None,
) -> int:
    """扫描入站 message.segments 的媒体, HTTP 下载落盘, 回填 media_uri。

    返回成功下载落盘的 segment 数。artifact_store 为 None 时直接返回 0 (未启用)。
    http_client 可注入 (测试); 生产用 httpx.AsyncClient。
    """
    segments = getattr(message, "segments", None) or []
    if not segments or artifact_store is None:
        return 0
    downloaded = 0
    for seg in segments:
        kind = _SEGMENT_KIND.get(getattr(seg, "type", ""))
        if kind is None:
            continue
        data = getattr(seg, "data", None) or {}
        url = data.get("url") or data.get("file")
        if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue  # 非 HTTP URL (本地路径等) 跳过
        if not is_safe_url(url):
            logger.warning("入站媒体 URL 不安全 (SSRF 拒绝), 跳过", url=url)
            continue
        try:
            content = await _download_bytes(url, http_client)
            if content is None:
                continue
            mime_type = _infer_mime(kind, url)
            ref = await artifact_store.put(content, kind=kind, mime_type=mime_type)
            data["media_uri"] = ref.uri
            downloaded += 1
            logger.info("入站媒体已下载落盘", kind=kind, url=url, artifact_id=ref.artifact_id)
        except Exception as exc:  # noqa: BLE001 异常隔离
            logger.warning("入站媒体下载落盘失败, 跳过该 segment", url=url, error=str(exc))
    return downloaded


async def _download_bytes(url: str, http_client: Any) -> bytes | None:
    """HTTP 下载为 bytes。http_client 注入时直接用; 否则走 safe_download_bytes。

    Fix-39: 生产路径改用 safe_download_bytes —— 重定向逐跳复跑 is_safe_url
    (此前 follow_redirects=True 不校验重定向目标 → SSRF 绕过), 且流式累计
    超过 MAX_INBOUND_MEDIA_BYTES 中止 (此前 resp.content 全量缓冲无上限 → OOM)。
    """
    if http_client is not None:
        return await http_client.get_bytes(url)
    return await safe_download_bytes(url, timeout_seconds=30.0, max_bytes=MAX_INBOUND_MEDIA_BYTES)


def _infer_mime(kind: str, url: str) -> str:
    """从 URL 后缀推断 MIME (best-effort; 无后缀按 kind 默认)。"""
    ext = url.rsplit(".", 1)[-1].lower() if "." in url else ""
    defaults = {"image": "image/png", "audio": "audio/mpeg", "video": "video/mp4", "file": "application/octet-stream"}
    ext_map = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
        "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4", "ogg": "audio/ogg",
        "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
        "pdf": "application/pdf", "txt": "text/plain",
    }
    if ext in ext_map:
        return ext_map[ext]
    return defaults.get(kind, "application/octet-stream")
