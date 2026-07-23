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

# 请求边界默认值 (CODE_REVIEW_REPORT.md #14): 防止超大 body / 慢速请求 / 无限连接占死服务
DEFAULT_MAX_BODY_BYTES = 1024 * 1024  # 1MB
DEFAULT_READ_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_CONNECTIONS = 200


class _RequestTooLarge(Exception):
    """Content-Length 超过上限, 在读取 body 前立即拒绝, 避免为超大 body 分配内存。"""


class WebChatAdapter(PlatformAdapter):
    """WebChat 适配器: HTTP 入口 + 内存消息队列。"""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._bind_host = str(config.get("bind_host", "127.0.0.1"))
        self._bind_port = int(config.get("bind_port", 8090))
        self._max_age = int(config.get("max_message_age_seconds", 300))
        self._max_body_bytes = int(config.get("max_body_bytes", DEFAULT_MAX_BODY_BYTES))
        self._read_timeout_seconds = float(
            config.get("read_timeout_seconds", DEFAULT_READ_TIMEOUT_SECONDS)
        )
        self._max_connections = int(config.get("max_connections", DEFAULT_MAX_CONNECTIONS))
        self._connection_semaphore = asyncio.Semaphore(self._max_connections)
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
        """极简 HTTP handler: 解析 path + body, 路由到 receive_from_client / poll_replies。

        用 semaphore 限制并发连接数, 用 timeout 包装请求读取, 避免慢速/不完整/超大
        请求无限占用连接资源 (CODE_REVIEW_REPORT.md #14)。
        """
        async with self._connection_semaphore:
            try:
                async with asyncio.timeout(self._read_timeout_seconds):
                    parsed = await self._read_request(reader)
                if parsed is None:
                    return
                method, path, body = parsed
                response_body, status = await self._route(method, path, body)
                await self._write_response(writer, status, response_body)
            except TimeoutError:
                await self._write_response(writer, 408, b'{"error":"request timeout"}')
            except _RequestTooLarge:
                await self._write_response(writer, 413, b'{"error":"payload too large"}')
            except Exception as exc:  # noqa: BLE001
                logger.warning("WebChat HTTP 处理异常", error=str(exc))
            finally:
                writer.close()
                await writer.wait_closed()

    async def _read_request(self, reader: asyncio.StreamReader) -> tuple[str, str, bytes] | None:
        """读取请求行 + headers + body。请求行不合法返回 None (静默关闭, 与原实现一致)。"""
        request_line = await reader.readline()
        if not request_line:
            return None
        parts = request_line.decode("utf-8", errors="replace").split()
        if len(parts) < 3:
            return None
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
        if content_length > self._max_body_bytes:
            # 在读取 body 前立即拒绝, 不为超大 body 等待/分配内存
            raise _RequestTooLarge(content_length)
        body = b""
        if content_length > 0:
            body = await reader.readexactly(content_length)
        return method, path, body

    async def _write_response(self, writer: asyncio.StreamWriter, status: int, body: bytes) -> None:
        """统一写 HTTP 响应 (从原 _handle_connection 内联逻辑抽取, 供正常/超时/超限分支复用)。"""
        response = (
            f"HTTP/1.1 {status} OK\r\n"
            f"Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode() + body
        writer.write(response)
        await writer.drain()

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
