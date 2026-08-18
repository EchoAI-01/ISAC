"""Telegram Bot API 适配器 (ARCHITECTURE.md 3.2 / SPECIFICATION.md 2.1)。

通过 Telegram Bot HTTP API (getUpdates long polling + sendMessage) 收发消息。
不依赖外部 SDK, 用 httpx 直接调用。

配置示例 (data/config.jsonc):
    {
        "channels": {
            "telegram": {
                "enabled": true,
                "bot_token": "123456:ABC-...",
                "api_base": "https://api.telegram.org",  // 可选, 默认官方
                "poll_timeout": 30,                      // long polling 秒数
                "retry_interval": 5
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
from isac.channel.text_chunk import chunk_text
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# Fix-98: Telegram 单条文本上限 (sendMessage text 4096 字符)
_TELEGRAM_MAX_TEXT_CHARS = 4096


def _utf16_slice(text: str, offset: int, length: int) -> str:
    """Fix-71: 按 UTF-16 code unit 切片 (Telegram entity 的 offset/length 单位)。

    Bot API 的 MessageEntity offset/length 以 UTF-16 code unit 计, 而 Python str
    下标是 code point。实体之前或内部出现 BMP 外字符 (emoji 🎉 / CJK 扩展 B 等,
    占 2 个 UTF-16 unit、1 个 code point) 时, 直接 content[offset:offset+length]
    会整体错位: mention 截出的文本缺 @ 或截半个词, strip("@") 后得到带空格/残缺
    的 user_id, @ 判定与后续按名寻人都失效。转 UTF-16 字节再切可精确对齐。
    """
    if offset < 0 or length <= 0:
        return ""
    units = text.encode("utf-16-le")
    return units[offset * 2 : (offset + length) * 2].decode("utf-16-le", errors="replace")


class TelegramAdapter(PlatformAdapter):
    """Telegram Bot API 适配器 (long polling 模式)。"""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._bot_token = str(config.get("bot_token", ""))
        self._api_base = str(config.get("api_base", "https://api.telegram.org"))
        self._poll_timeout = int(config.get("poll_timeout", 30))
        self._retry_interval = float(config.get("retry_interval", 5))
        self._running = False
        self._poll_task: asyncio.Task[Any] | None = None
        self._offset = 0  # getUpdates offset (只取新消息)
        self._http_client: Any = None  # 惰性创建 httpx.AsyncClient

    @property
    def platform_name(self) -> str:
        return "telegram"

    async def start(self) -> None:
        """启动 long polling。"""
        if not self._bot_token:
            raise RuntimeError("Telegram bot_token 未配置")
        self._running = True
        # getMe 验证 token 有效
        me = await self._call_api("getMe")
        if me is None:
            raise RuntimeError("Telegram bot_token 无效或网络异常")
        logger.info("Telegram Bot 已连接", bot_username=me.get("username"))
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
        """发送文本消息到 Telegram。

        Fix-98: Telegram 单条上限 4096 字符, 超长整条提交 → 平台 400 → 回复静默
        丢失。按上限分段发送 (优先换行边界); 任一段失败整体记 False 但继续发余下段。
        """
        chat_id = message.group_id or message.user_id
        if not chat_id:
            logger.warning("Telegram send 缺少 chat_id", msg_id=message.msg_id)
            return False
        chunks = chunk_text(str(message.content or ""), _TELEGRAM_MAX_TEXT_CHARS)
        if not chunks:
            chunks = [""]
        ok = True
        for index, chunk in enumerate(chunks):
            params: dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
            }
            # 仅首段带 reply_to (避免每段都挂引用)
            if index == 0 and message.reply_to:
                params["reply_to_message_id"] = message.reply_to
            result = await self._call_api("sendMessage", params)
            if result is None:
                ok = False
        return ok

    async def _poll_loop(self) -> None:
        """long polling 主循环, 失败重试。"""
        while self._running:
            try:
                updates = await self._call_api(
                    "getUpdates",
                    {
                        "offset": self._offset,
                        "timeout": self._poll_timeout,
                        "allowed_updates": ["message"],
                    },
                )
                if updates is None:
                    if self._running:
                        await asyncio.sleep(self._retry_interval)
                    continue
                for update in updates:
                    self._offset = update.get("update_id", self._offset) + 1
                    await self._handle_update(update)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("Telegram poll 异常, 重试", error=str(exc))
                await asyncio.sleep(self._retry_interval)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        """把 Telegram update 转成 ISACMessage 并交给 on_message 回调。"""
        message = update.get("message")
        if message is None:
            return
        isac_msg = self._to_isac_message(message)
        if isac_msg is None:
            return
        if self.on_message is not None:
            try:
                await self.on_message(isac_msg)
            except Exception as exc:  # noqa: BLE001
                logger.error("Telegram 消息处理回调异常", error=str(exc), exc_info=True)

    def _to_isac_message(self, tg_message: dict[str, Any]) -> ISACMessage | None:
        """Telegram message → ISACMessage。"""
        msg_id = str(tg_message.get("message_id", ""))
        if not msg_id:
            return None
        chat = tg_message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        from_user = tg_message.get("from", {})
        user_id = str(from_user.get("id", ""))
        user_name = from_user.get("username") or from_user.get("first_name", "")
        chat_type = chat.get("type", "private")
        group_id = chat_id if chat_type in ("group", "supergroup") else None
        content = str(tg_message.get("text", "") or "")
        segments: list[MessageSegment] = []
        # 处理 entities (如 @mention)
        for entity in tg_message.get("entities", []) or []:
            etype = entity.get("type", "")
            if etype == "mention":
                offset = int(entity.get("offset", 0))
                length = int(entity.get("length", 0))
                # Fix-71: offset/length 是 UTF-16 code unit, 不能按 code point 直切
                mention_text = _utf16_slice(content, offset, length)
                segments.append(MessageSegment(type="at", data={"user_id": mention_text.strip("@")}))
        if not segments and content:
            segments.append(MessageSegment(type="text", data={"text": content}))
        return ISACMessage(
            msg_id=msg_id,
            platform=self.platform_name,
            timestamp=int(tg_message.get("date", time.time())),
            user_id=user_id,
            user_name=user_name,
            group_id=group_id,
            content=content,
            segments=segments,
        )

    async def _call_api(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """调用 Telegram Bot API。返回 result 字段 (失败返回 None)。"""
        try:
            import httpx
        except ImportError:
            logger.error("httpx 未安装, Telegram 适配器不可用")
            return None
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=max(30, self._poll_timeout + 5))
        url = f"{self._api_base}/bot{self._bot_token}/{method}"
        try:
            response = await self._http_client.post(url, json=params or {})
            data = response.json()
            if not data.get("ok"):
                logger.warning("Telegram API 返回错误", method=method, description=data.get("description"))
                return None
            return data.get("result")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram API 调用异常", method=method, error=str(exc))
            return None
