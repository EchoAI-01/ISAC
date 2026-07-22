"""WebChat 适配器 (ARCHITECTURE.md 3.2 / SPECIFICATION.md 2.1)。

提供 HTTP POST /webchat/send (用户消息) 与 GET /webchat/poll (客户端拉取回复) 接口。
不依赖 WebSocket, 用简单的 polling 模式, 适合本地测试与轻量部署。

配置示例 (data/config.jsonc):
    {
        "channels": {
            "webchat": {
                "enabled": true,
                "bind_host": "127.0.0.1",
                "bind_port": 8090,
                "max_message_age_seconds": 300  // 未消费消息过期时间
            }
        }
    }
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from isac.channel.base import PlatformAdapter
from isac.channel.model import ISACMessage, MessageSegment
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class WebChatAdapter(PlatformAdapter):
    """WebChat 适配器: HTTP 入口 + 内存消息队列。"""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._bind_host = str(config.get("bind_host", "127.0.0.1"))
        self._bind_port = int(config.get("bind_port", 8090))
        self._max_age = int(config.get("max_message_age_seconds", 300))
        self._running = False
        # session_id -> 待消费的回复列表 [(timestamp, content)]
        self._pending_replies: dict[str, list[tuple[float, str]]] = {}
        self._lock = asyncio.Lock()
        self._http_server: Any = None

    @property
    def platform_name(self) -> str:
        return "webchat"

    async def start(self) -> None:
        """启动内置 HTTP 服务器 (使用 asyncio.start_server 极简实现)。"""
        self._running = True
        try:
            self._http_server = await asyncio.start_server(
                self._handle_connection,
                host=self._bind_host,
                port=self._bind_port,
            )
        except OSError as exc:
            logger.error("WebChat 服务器绑定失败", host=self._bind_host, port=self._bind_port, error=str(exc))
            raise
        logger.info("WebChat 适配器已启动", host=self._bind_host, port=self._bind_port)

    async def stop(self) -> None:
        """停止服务器并清理。"""
        self._running = False
        if self._http_server is not None:
            self._http_server.close()
            await self._http_server.wait_closed()
            self._http_server = None

    async def send(self, message: ISACMessage) -> bool:
        """把 Bot 回复存入 session 的待消费队列。"""
        session_id = message.session_id or message.group_id or message.user_id
        if not session_id:
            logger.warning("WebChat send 缺少 session_id")
            return False
        async with self._lock:
            queue = self._pending_replies.setdefault(session_id, [])
            queue.append((time.time(), message.content))
        return True

    async def receive_from_client(self, session_id: str, user_id: str, content: str) -> None:
        """HTTP /webchat/send 调用: 把用户消息转成 ISACMessage 触发 on_message。"""
        if not content or not self.on_message:
            return
        msg = ISACMessage(
            msg_id=f"webchat-{int(time.time() * 1000)}",
            platform=self.platform_name,
            timestamp=int(time.time()),
            user_id=user_id,
            user_name=user_id,
            group_id=None,
            session_id=session_id,
            content=content,
            segments=[MessageSegment(type="text", data={"text": content})],
        )
        try:
            await self.on_message(msg)
        except Exception as exc:  # noqa: BLE001
            logger.error("WebChat 消息回调异常", error=str(exc), exc_info=True)

    async def poll_replies(self, session_id: str) -> list[dict[str, Any]]:
        """HTTP /webchat/poll 调用: 拉取并清空该 session 的待消费回复。"""
        now = time.time()
        async with self._lock:
            queue = self._pending_replies.get(session_id, [])
            # 过滤掉超时的
            valid = [(ts, content) for ts, content in queue if now - ts < self._max_age]
            self._pending_replies[session_id] = []
        return [{"timestamp": ts, "content": content} for ts, content in valid]

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """极简 HTTP handler: 解析 path + body, 路由到 receive_from_client / poll_replies。"""
        try:
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                await writer.wait_closed()
                return
            parts = request_line.decode("utf-8", errors="replace").split()
            if len(parts) < 3:
                writer.close()
                await writer.wait_closed()
                return
            method, path, _ = parts[0], parts[1], parts[2]
            # 读 headers 直到空行
            content_length = 0
            while True:
                header_line = await reader.readline()
                if header_line in (b"\r\n", b"\n", b""):
                    break
                header_str = header_line.decode("utf-8", errors="replace").lower()
                if header_str.startswith("content-length:"):
                    content_length = int(header_str.split(":", 1)[1].strip())
            body = b""
            if content_length > 0:
                body = await reader.readexactly(content_length)
            response_body, status = await self._route(method, path, body)
            response = (
                f"HTTP/1.1 {status} OK\r\n"
                f"Content-Type: application/json; charset=utf-8\r\n"
                f"Content-Length: {len(response_body)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode() + response_body
            writer.write(response)
            await writer.drain()
        except Exception as exc:  # noqa: BLE001
            logger.warning("WebChat HTTP 处理异常", error=str(exc))
        finally:
            writer.close()
            await writer.wait_closed()

    async def _route(self, method: str, path: str, body: bytes) -> tuple[bytes, int]:
        """根据 path 路由到对应处理函数。"""
        import json
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(path)
        if method == "POST" and parsed.path == "/webchat/send":
            try:
                payload = json.loads(body.decode("utf-8"))
                await self.receive_from_client(
                    str(payload.get("session_id", "")),
                    str(payload.get("user_id", "")),
                    str(payload.get("content", "")),
                )
                return b'{"status":"ok"}', 200
            except Exception as exc:  # noqa: BLE001
                err = json.dumps({"error": str(exc)}).encode("utf-8")
                return err, 400
        if method == "GET" and parsed.path == "/webchat/poll":
            query = parse_qs(parsed.query)
            session_id = query.get("session_id", [""])[0]
            replies = await self.poll_replies(session_id)
            return json.dumps({"replies": replies}).encode("utf-8"), 200
        return b'{"error":"not found"}', 404
