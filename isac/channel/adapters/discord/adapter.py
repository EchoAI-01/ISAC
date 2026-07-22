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
import time
from typing import TYPE_CHECKING, Any

from isac.channel.base import PlatformAdapter
from isac.channel.model import ISACMessage, MessageSegment
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class DiscordAdapter(PlatformAdapter):
    """Discord REST API 适配器 (polling 模式, 简化版)。"""

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
        logger.info("Discord Bot 已连接", bot_username=me.get("username"))
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
        """发送文本消息到 Discord channel。"""
        channel_id = message.group_id or message.user_id
        if not channel_id:
            logger.warning("Discord send 缺少 channel_id")
            return False
        result = await self._call_api(
            "POST",
            f"/channels/{channel_id}/messages",
            json_body={"content": message.content},
        )
        return result is not None

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
        """拉取单 channel 的最新消息。"""
        params: dict[str, Any] = {"limit": 10}
        last_id = self._last_message_ids.get(channel_id)
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
        # 更新 last seen id
        if messages:
            self._last_message_ids[channel_id] = str(messages[0].get("id", last_id or ""))

    def _to_isac_message(self, dc_message: dict[str, Any], channel_id: str) -> ISACMessage | None:
        """Discord message → ISACMessage。"""
        msg_id = str(dc_message.get("id", ""))
        if not msg_id:
            return None
        author = dc_message.get("author", {})
        user_id = str(author.get("id", ""))
        user_name = author.get("username", "")
        content = str(dc_message.get("content", "") or "")
        # Discord 没有 group_id 概念, channel_id 作 group_id
        return ISACMessage(
            msg_id=msg_id,
            platform=self.platform_name,
            timestamp=int(time.mktime(time.strptime(dc_message.get("timestamp", "")[:19], "%Y-%m-%dT%H:%M:%S"))),
            user_id=user_id,
            user_name=user_name,
            group_id=channel_id,
            content=content,
            segments=[MessageSegment(type="text", data={"text": content})] if content else [],
        )

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
