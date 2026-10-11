"""Discord 适配器 (ARCHITECTURE.md 3.2 / SPECIFICATION.md 2.1)。

通过 Discord Bot HTTP API (Gateway WebSocket 简化为 REST polling + webhook) 收发消息。
不依赖 discord.py, 用 httpx 直接调用 REST API。

配置示例 (data/config.jsonc):
    {
        "channels": {
            "discord": {
                "enabled": true,
                "bot_token": "...",
                "api_base": "https://discord.com/api/v10",
                "poll_interval": 2,
                "watch_channel_ids": ["1234567890"]
            }
        }
    }

简化说明: Discord 官方推荐用 Gateway WebSocket 实时收消息; 本适配器为最小实现,
使用 REST polling (list messages) 适合测试场景。生产推荐接入 discord.py 或
官方 Gateway SDK。
"""

from __future__ import annotations

import asyncio
import calendar
import time
from typing import TYPE_CHECKING, Any

from isac.channel.base import PlatformAdapter
from isac.channel.model import ISACMessage, MessageSegment
from isac.channel.text_chunk import chunk_text
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# Fix-98: Discord 单条文本上限 (message content 2000 字符)
_DISCORD_MAX_TEXT_CHARS = 2000


class DiscordAdapter(PlatformAdapter):
    """Discord REST API 适配器 (polling 模式, 简化版)。"""

    _MAX_POLL_PAGES = 20  # 单轮 poll 最多翻的页数, 避免异常场景下无限拉取

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._bot_token = str(config.get("bot_token", ""))
        self._api_base = str(config.get("api_base", "https://discord.com/api/v10"))
        self._poll_interval = float(config.get("poll_interval", 2))
        self._watch_channels: list[str] = list(config.get("watch_channel_ids", []))
        self._running = False
        self._poll_task: asyncio.Task[Any] | None = None
        self._last_message_ids: dict[str, str] = {}  # channel_id -> last seen message id
        self._http_client: Any = None
        # N5b 批次G: 缓存 Bot 自身 user_id, _to_isac_message 据此过滤自身发出的消息,
        # 避免 REST polling 把 Bot 回复当入站消息重新 dispatch → 自回应死循环。
        self._bot_user_id: str = ""

    @property
    def platform_name(self) -> str:
        return "discord"

    async def start(self) -> None:
        """启动 polling。"""
        if not self._bot_token:
            raise RuntimeError("Discord bot_token 未配置")
        if not self._watch_channels:
            logger.warning("Discord watch_channel_ids 未配置, 无消息可监听")
        self._running = True
        # 验证 token
        me = await self._call_api("GET", "/users/@me")
        if me is None:
            raise RuntimeError("Discord bot_token 无效或网络异常")
        # N5b 批次G: 缓存 Bot 自身 user_id 用于过滤自身发出的消息 (REST polling 返回
        # 频道内全部消息含 Bot 回复, 不过滤则回复被重新当入站 → 自回应死循环)。
        self._bot_user_id = str(me.get("id", "") or "")
        logger.info("Discord Bot 已连接", bot_username=me.get("username"), bot_user_id=self._bot_user_id)
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """停止 polling 并清理。"""
        self._running = False
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def send(self, message: ISACMessage) -> bool:
        """发送文本/附件消息到 Discord channel。

        Fix-98: Discord 单条上限 2000 字符, 超长整条提交 → 平台 400 → 回复静默
        丢失。按上限分段发送 (优先换行边界); 任一段失败整体记 False 但继续发余下段。
        富媒体二波 (2026-10-11): segments 含 image/video/audio/file 段时, 读本地
        制品文件以 multipart 附件发送 (与文本同一条消息, payload_json+files[0]);
        附件读取失败降级占位文本不阻塞文本段。
        """
        channel_id = message.group_id or message.user_id
        if not channel_id:
            logger.warning("Discord send 缺少 channel_id")
            return False
        # 富媒体二波: 本地制品附件 (有则与首段文本合并为 multipart 消息)
        attachments = await self._collect_local_attachments(message)
        chunks = chunk_text(str(message.content or ""), _DISCORD_MAX_TEXT_CHARS)
        if not chunks:
            chunks = [""]
        ok = True
        for i, chunk in enumerate(chunks):
            if i == 0 and attachments:
                result = await self._send_multipart(channel_id, chunk, attachments)
                attachments = []  # 附件只随首条, 余下纯文本
            else:
                result = await self._call_api(
                    "POST",
                    f"/channels/{channel_id}/messages",
                    json_body={"content": chunk},
                )
            if result is None:
                ok = False
        return ok

    @staticmethod
    async def _collect_local_attachments(message: ISACMessage) -> list[tuple[str, bytes, str]]:
        """收集 segments 中可读的本地制品附件 → [(文件名, bytes, mime)]。

        仅接受本地路径 (media_uri/url 指向 ArtifactStore 落盘文件); 平台回传
        URL (http) 不重传 (无本地字节), 跳过。单附件失败隔离。
        """
        import mimetypes
        from pathlib import Path

        out: list[tuple[str, bytes, str]] = []
        for seg in message.segments or []:
            seg_type = getattr(seg, "type", "")
            if seg_type not in ("image", "video", "audio", "voice", "file"):
                continue
            data = getattr(seg, "data", None) or {}
            local_path = str(data.get("media_uri") or data.get("url") or "")
            if not local_path or local_path.startswith(("http://", "https://")):
                continue
            try:
                # N5: 附件可能数 MB, 同步读盘会阻塞事件循环 —— 迁 to_thread。
                content = await asyncio.to_thread(Path(local_path).read_bytes)
            except Exception as exc:  # noqa: BLE001 单附件失败隔离
                logger.warning("Discord 附件读取失败, 跳过", path=str(local_path)[:120], error=str(exc))
                continue
            name = Path(local_path).name or "attachment"
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            out.append((name, content, mime))
        return out

    async def _send_multipart(
        self, channel_id: str, content: str, attachments: list[tuple[str, bytes, str]]
    ) -> Any:
        """multipart 附件消息 (payload_json + files[N]); 失败降级纯文本重发。"""
        try:
            import json as _json

            files = [
                (f"files[{i}]", (name, blob, mime)) for i, (name, blob, mime) in enumerate(attachments)
            ]
            if self._http_client is None:
                await self._call_api("GET", "/users/@me")  # 惰性建 client (含鉴权头)
            response = await self._http_client.post(
                f"/channels/{channel_id}/messages",
                data={"payload_json": _json.dumps({"content": content})},
                files=files,
            )
            if response.status_code >= 400:
                logger.warning(
                    "Discord multipart 发送 HTTP 错误",
                    status=response.status_code, body=response.text[:200],
                )
                return await self._call_api(
                    "POST", f"/channels/{channel_id}/messages", json_body={"content": content}
                )
            if response.status_code == 204:
                return {}
            return response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Discord multipart 发送异常, 降级纯文本", error=str(exc))
            return await self._call_api(
                "POST", f"/channels/{channel_id}/messages", json_body={"content": content}
            )

    async def _poll_loop(self) -> None:
        """轮询 watch_channels 拉新消息。"""
        while self._running:
            try:
                for channel_id in self._watch_channels:
                    await self._poll_channel(channel_id)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("Discord poll 异常, 重试", error=str(exc))
            await asyncio.sleep(self._poll_interval)

    async def _poll_channel(self, channel_id: str) -> None:
        """拉取单 channel 的新消息。

        单页 limit=10, 若本轮积压超过一页, 循环翻页直到拿完本轮所有新消息或
        达到页数上限, 每页完整处理 (全部 dispatch 给 on_message) 后才提交 cursor,
        避免只拉一页导致中间消息永远排不到 (CODE_REVIEW_REPORT.md #16)。
        """
        page_limit = 10
        last_id = self._last_message_ids.get(channel_id)
        for _ in range(self._MAX_POLL_PAGES):
            params: dict[str, Any] = {"limit": page_limit}
            if last_id:
                params["after"] = last_id
            messages = await self._call_api("GET", f"/channels/{channel_id}/messages", query=params)
            if not messages:
                return
            # Discord REST 返回最新→最旧, 倒序处理后发
            for msg in reversed(messages):
                isac_msg = self._to_isac_message(msg, channel_id)
                if isac_msg is None:
                    continue
                if self.on_message is not None:
                    try:
                        await self.on_message(isac_msg)
                    except Exception as exc:  # noqa: BLE001
                        logger.error("Discord 消息回调异常", error=str(exc), exc_info=True)
            last_id = str(messages[0].get("id", last_id or ""))
            self._last_message_ids[channel_id] = last_id
            if len(messages) < page_limit:
                return  # 本页未填满, 说明没有更多新消息了

    def _to_isac_message(self, dc_message: dict[str, Any], channel_id: str) -> ISACMessage | None:
        """Discord message → ISACMessage。"""
        msg_id = str(dc_message.get("id", ""))
        if not msg_id:
            return None
        author = dc_message.get("author", {})
        # N5b 批次G: 丢弃 Bot 自身发出的消息 (author.bot 标志或 id==bot_user_id),
        # 否则 REST polling 把 Bot 回复当入站消息重新 dispatch → 自回应死循环。
        if author.get("bot") or (self._bot_user_id and str(author.get("id", "")) == self._bot_user_id):
            return None
        user_id = str(author.get("id", ""))
        user_name = author.get("username", "")
        content = str(dc_message.get("content", "") or "")
        # 富媒体二波: 解析 attachments (Discord CDN url 签名公开可下载) → media
        # segment (供入站下载管线落盘 data/uploads)。kind 按 content_type 前缀。
        segments: list[MessageSegment] = []
        if content:
            segments.append(MessageSegment(type="text", data={"text": content}))
        segments.extend(self._build_attachment_segments(dc_message.get("attachments")))
        # Discord 没有 group_id 概念, channel_id 作 group_id
        return ISACMessage(
            msg_id=msg_id,
            platform=self.platform_name,
            timestamp=self._parse_timestamp(dc_message.get("timestamp", "")),
            user_id=user_id,
            user_name=user_name,
            group_id=channel_id,
            content=content,
            segments=segments,
        )

    @staticmethod
    def _build_attachment_segments(attachments: Any) -> list[MessageSegment]:
        """Discord attachments 数组 → media segment 列表。

        CDN url 带签名参数 (公开可下载, 无需鉴权头); content_type 前缀映射
        image/video/audio → 对应 kind, 其余 file。异常/缺失字段跳过 (单项隔离)。
        """
        if not isinstance(attachments, list):
            return []
        out: list[MessageSegment] = []
        for att in attachments:
            if not isinstance(att, dict):
                continue
            url = str(att.get("url", "") or "")
            if not url.startswith(("http://", "https://")):
                continue
            content_type = str(att.get("content_type", "") or "")
            if content_type.startswith("image/"):
                kind = "image"
            elif content_type.startswith("video/"):
                kind = "video"
            elif content_type.startswith("audio/"):
                kind = "audio"
            else:
                kind = "file"
            data: dict[str, Any] = {"url": url}
            filename = str(att.get("filename", "") or "")
            if filename:
                data["file_name"] = filename
            out.append(MessageSegment(type=kind, data=data))
        return out

    @staticmethod
    def _parse_timestamp(raw: Any) -> int:
        """解析 Discord ISO8601 时间戳 → Unix 秒。

        CR3-Fix: 此前直接 time.mktime(time.strptime(raw[:19])) 有两处缺陷:
        (1) raw 缺失/格式异常时 strptime 抛 ValueError, 且本方法在 _poll_channel
            的 cursor 提交之前调用、异常会逃逸到轮询循环, 使该 channel 永远重拉同一页
            (cursor 不前进) —— 单条坏消息即可拖死整条频道。
        (2) Discord 时间戳是 UTC, 但 time.mktime 按本地时区解释, 结果偏移一个时区。
        改为 calendar.timegm (按 UTC 解释) 并对解析失败兜底为当前时间, 保证健壮。
        """
        try:
            return calendar.timegm(time.strptime(str(raw)[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError):
            return int(time.time())

    async def _call_api(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        """调用 Discord REST API。"""
        try:
            import httpx
        except ImportError:
            logger.error("httpx 未安装, Discord 适配器不可用")
            return None
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url=self._api_base,
                headers={"Authorization": f"Bot {self._bot_token}"},
                timeout=30,
            )
        try:
            response = await self._http_client.request(method, path, json=json_body, params=query)
            if response.status_code >= 400:
                logger.warning(
                    "Discord API 错误",
                    method=method,
                    path=path,
                    status=response.status_code,
                    body=response.text[:200],
                )
                return None
            if response.status_code == 204:
                return {}
            return response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Discord API 调用异常", method=method, path=path, error=str(exc))
            return None
