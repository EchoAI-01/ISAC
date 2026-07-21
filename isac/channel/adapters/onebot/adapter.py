"""OneBot v11 平台适配器 (反向 WebSocket / HTTP)。

决策点 (DEVELOPMENT_PLAN.md C1): OneBot v11 (aiocqhttp)，生态更成熟。
联调准备: NapCat + 测试 QQ 号 + 测试群。

配置示例 (data/config.jsonc):
    {
        "channels": {
            "onebot": {
                "enabled": true,
                "host": "127.0.0.1",
                "port": 8080,
                "access_token": "",
                "retry_interval": 5,       // 重试间隔 (秒)
                "max_retries": 10          // 最大连续重试次数，-1 无限
            }
        },
        "bot_id": "123456789"             // Bot 的 QQ 号，用于 has_at 判定
    }
"""

from __future__ import annotations

import asyncio
from typing import Any

from isac.channel.base import PlatformAdapter
from isac.channel.model import ISACMessage, MessageSegment
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class OneBotAdapter(PlatformAdapter):
    """OneBot v11 适配器。

    当前主要实现 **反向 WebSocket** 模式：ISAC 作为服务端运行，NapCat 主动连接。
    只在 ``start()`` / ``send()`` 等运行时才导入 aiocqhttp，避免未安装 onebot extra 时
    导入本模块直接崩溃。
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._bot: Any = None
        self._server_task: asyncio.Task[Any] | None = None
        self._running = False
        self._retry_count = 0
        self._retry_interval = float(config.get("retry_interval", 5))
        self._max_retries = int(config.get("max_retries", 10))

    def _ensure_imports(self) -> tuple[Any, Any, Any]:
        """惰性导入 aiocqhttp；未安装时给出友好错误。"""
        try:
            from aiocqhttp import CQHttp
            from aiocqhttp import Error as CQHttpError
            from aiocqhttp import MessageSegment as CQSegment
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "OneBot 适配器需要 aiocqhttp。请运行: uv sync --extra onebot"
            ) from exc
        return CQHttp, CQHttpError, CQSegment

    def _init_bot(self) -> None:
        """初始化 CQHttp 实例（按需）。"""
        if self._bot is not None:
            return
        CQHttp, _CQHttpError, _CQSegment = self._ensure_imports()
        self._bot = CQHttp(
            api_root=None,  # 反向 WS 模式不通过 HTTP API 根调用
            access_token=self.config.get("access_token") or None,
            message_class=None,
        )

        # 注册 OneBot 事件处理器
        self._bot.on_message(self._on_cq_message)
        self._bot.on_notice(self._on_cq_notice)
        self._bot.on_request(self._on_cq_request)
        self._bot.on_meta_event(self._on_cq_meta_event)

    @property
    def platform_name(self) -> str:
        return "qq"

    async def start(self) -> None:
        """启动 OneBot 服务端（反向 WebSocket）。"""
        if self._running:
            logger.warning("OneBot 适配器已在运行")
            return
        self._init_bot()
        self._running = True
        host = self.config.get("host", "127.0.0.1")
        port = int(self.config.get("port", 8080))
        self._server_task = asyncio.create_task(
            self._run_with_retry(host, port),
            name="onebot-server",
        )
        logger.info("OneBot 适配器已启动", host=host, port=port, mode=self.config.get("mode", "reverse_ws"))

    async def stop(self) -> None:
        """停止服务端并清理资源。"""
        self._running = False
        if self._server_task and not self._server_task.done():
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
        self._server_task = None
        logger.info("OneBot 适配器已停止")

    async def send(self, message: ISACMessage) -> bool:
        """发送消息到 OneBot 平台。"""
        self._init_bot()
        _CQHttp, CQHttpError, _CQSegment = self._ensure_imports()
        cq_message = self._to_cq_message(message)
        try:
            if message.group_id:
                await self._bot.call_action(
                    "send_group_msg",
                    group_id=message.group_id,
                    message=cq_message,
                )
            else:
                await self._bot.call_action(
                    "send_private_msg",
                    user_id=message.user_id,
                    message=cq_message,
                )
            return True
        except CQHttpError as exc:
            logger.warning("OneBot 发送失败", error=str(exc), group_id=message.group_id, user_id=message.user_id)
            return False
        except Exception as exc:  # pragma: no cover
            logger.error("OneBot 发送异常", error=str(exc), exc_info=True)
            return False

    # ── 内部：服务端启动与重试 ─────────────────────────────────

    async def _run_with_retry(self, host: str, port: int) -> None:
        """带指数退避的服务端启动循环。"""
        while self._running:
            try:
                await self._bot.run_task(host=host, port=port)
                # 正常结束（stop() 被调用）
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._retry_count += 1
                if self._max_retries >= 0 and self._retry_count > self._max_retries:
                    logger.error("OneBot 服务端重试次数耗尽，停止", error=str(exc), retries=self._retry_count)
                    break
                logger.warning(
                    "OneBot 服务端异常，准备重连",
                    error=str(exc),
                    retry=self._retry_count,
                    interval=self._retry_interval,
                )
                await asyncio.sleep(self._retry_interval)
                # 简单的指数退避，上限 60 秒
                self._retry_interval = min(self._retry_interval * 1.5, 60.0)

    # ── 内部：OneBot → ISACMessage ────────────────────────────

    async def _on_cq_message(self, event: Any) -> None:
        """处理 OneBot 消息事件。"""
        try:
            message = self._parse_message_event(event)
        except Exception as exc:
            logger.warning("OneBot 消息事件解析失败", error=str(exc), exc_info=True)
            return
        await self._dispatch(message)

    async def _on_cq_notice(self, event: Any) -> None:
        """处理通知事件（目前仅记录，可按需扩展）。"""
        logger.debug("OneBot 通知事件", event_type=getattr(event, "notice_type", "unknown"))

    async def _on_cq_request(self, event: Any) -> None:
        """处理请求事件（好友/群申请，目前仅记录）。"""
        logger.debug("OneBot 请求事件", event_type=getattr(event, "request_type", "unknown"))

    async def _on_cq_meta_event(self, event: Any) -> None:
        """处理元事件（心跳/生命周期），收到连接事件时重置重试计数。"""
        meta_type = getattr(event, "meta_event_type", "unknown")
        if meta_type == "lifecycle" and getattr(event, "sub_type", "") == "connect":
            self._retry_count = 0
            self._retry_interval = float(self.config.get("retry_interval", 5))
            logger.info("OneBot 客户端已连接")
        logger.debug("OneBot 元事件", meta_event_type=meta_type)

    def _parse_message_event(self, event: Any) -> ISACMessage:
        """把 aiocqhttp 消息事件转换为 ISACMessage。"""
        message_id = str(getattr(event, "message_id", ""))
        user_id = str(getattr(event, "user_id", ""))
        group_id_raw = getattr(event, "group_id", None)
        group_id = str(group_id_raw) if group_id_raw is not None else None
        sender = getattr(event, "sender", {}) or {}
        # 群聊优先使用群名片 (card)，私聊使用昵称 (nickname)
        user_name = sender.get("card", "") or sender.get("nickname", "") or user_id
        timestamp = int(getattr(event, "time", 0))
        raw_message = getattr(event, "message", "")

        segments = self._from_cq_message(raw_message)
        content = self._extract_text(segments)

        reply_to = None
        for seg in segments:
            if seg.type == "reply":
                reply_to = str(seg.data.get("id", ""))
                break

        return ISACMessage(
            msg_id=message_id,
            platform=self.platform_name,
            timestamp=timestamp,
            user_id=user_id,
            user_name=user_name,
            group_id=group_id,
            content=content,
            segments=segments,
            reply_to=reply_to,
            metadata={
                "post_type": getattr(event, "post_type", None),
                "message_type": getattr(event, "message_type", None),
                "sub_type": getattr(event, "sub_type", None),
            },
        )

    def _from_cq_message(self, raw_message: Any) -> list[MessageSegment]:
        """把 CQ 消息对象/列表转换为 ISAC MessageSegment 列表。"""
        segments: list[MessageSegment] = []
        if raw_message is None:
            return segments

        # aiocqhttp 的 Message 是可迭代对象
        if hasattr(raw_message, "__iter__") and not isinstance(raw_message, str):
            for seg in raw_message:
                segments.append(self._convert_cq_segment(seg))
        else:
            # 兜底：按纯文本处理
            segments.append(MessageSegment(type="text", data={"text": str(raw_message)}))
        return segments

    def _convert_cq_segment(self, seg: Any) -> MessageSegment:
        """单个 CQ 消息段 → ISAC MessageSegment。"""
        if isinstance(seg, dict):
            seg_type = seg.get("type", "text")
            seg_data = seg.get("data", {})
        else:
            # aiocqhttp MessageSegment 是 dict 子类
            seg_type = getattr(seg, "type", "text")
            seg_data = dict(seg) if hasattr(seg, "items") else getattr(seg, "data", {})

        mapping: dict[str, str] = {
            "text": "text",
            "at": "at",
            "image": "image",
            "reply": "reply",
            "face": "emoji",
            "record": "voice",
        }
        isac_type = mapping.get(seg_type, "text")
        if isac_type == "text" and seg_type != "text":
            # 未识别的类型，保留原始文本字段作为兜底
            return MessageSegment(type="text", data={"text": str(seg_data)})
        # 统一字段名：OneBot at 用 "qq"，ISAC 统一用 "user_id"
        if isac_type == "at" and "qq" in seg_data and "user_id" not in seg_data:
            seg_data = {**seg_data, "user_id": seg_data["qq"]}
        return MessageSegment(type=isac_type, data=seg_data)

    def _extract_text(self, segments: list[MessageSegment]) -> str:
        """从 segment 列表提取纯文本。

        @ 段不展开为 QQ 号（避免 LLM 看到数字 ID 影响回复质量），
        保留为 "@某人" 占位；at 信息已通过 segments 单独传递给门控/工具。
        """
        parts: list[str] = []
        for seg in segments:
            if seg.type == "text":
                parts.append(str(seg.data.get("text", "")))
            elif seg.type == "at":
                parts.append("@某人")
        return "".join(parts)

    # ── 内部：ISACMessage → OneBot ────────────────────────────

    def _to_cq_message(self, message: ISACMessage) -> Any:
        """把 ISACMessage 转换为 CQ 消息。"""
        _CQHttp, _CQHttpError, CQSegment = self._ensure_imports()
        cq_segments: list[Any] = []
        # 如果顶层 reply_to 存在，先插入 reply 段（与入站解析对称）
        if message.reply_to:
            cq_segments.append(CQSegment.reply(message.reply_to))
        for seg in message.segments:
            converted = self._to_cq_segment(seg, CQSegment)
            if converted is not None:
                cq_segments.append(converted)
        if not cq_segments:
            return CQSegment.text(message.content)
        # aiocqhttp Message 支持 list[MessageSegment]
        return cq_segments

    def _to_cq_segment(self, seg: MessageSegment, CQSegment: Any) -> Any | None:
        """单个 ISAC MessageSegment → CQ 消息段。"""
        if seg.type == "text":
            return CQSegment.text(str(seg.data.get("text", "")))
        if seg.type == "at":
            user_id = seg.data.get("user_id", "")
            return CQSegment.at(str(user_id))
        if seg.type == "image":
            return CQSegment.image(seg.data.get("url", seg.data.get("file", "")))
        if seg.type == "reply":
            return CQSegment.reply(seg.data.get("msg_id", ""))
        if seg.type == "emoji":
            return CQSegment.face(seg.data.get("id", 0))
        if seg.type == "voice":
            return CQSegment.record(seg.data.get("url", seg.data.get("file", "")))
        # 不支持的类型降级为文本
        logger.debug("不支持的 ISACMessage segment 类型，已跳过", type=seg.type)
        return None

    async def _dispatch(self, message: ISACMessage) -> None:
        """分发到框架注册的 on_message 回调。"""
        if self.on_message is not None:
            try:
                await self.on_message(message)
            except Exception as exc:
                logger.error("OneBot 消息分发失败", error=str(exc), exc_info=True)
                if self.on_error is not None:
                    await self.on_error(exc)
