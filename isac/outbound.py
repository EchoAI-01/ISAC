"""U2 出站发送 (outbound): Agent 回复 / 进度帧经 Channel 适配器发送。

原 isac/dispatch.py 的出站三件套拆出 (第三轮审查批 2 后 dispatch 触 500 行红线);
dispatch.py 保留 re-export 供既有 import 路径不变。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from isac.channel.model import ISACMessage
from isac.channel.registry import ChannelRegistry
from isac.core.types import ProgressEvent
from isac.utils.logger import get_logger

logger = get_logger(__name__)


async def _send_reply(
    channel_registry: ChannelRegistry,
    incoming: ISACMessage,
    reply_text: str,
    agent_id: str,
    platform_session_id: str = "",
    *,
    artifact_store: Any = None,
) -> None:
    """把 Agent 的文本回复经原 Channel 适配器发送。

    Q0: platform_session_id 是 gateway 改写前的适配器侧会话键 (WebChat 客户端
    的 session_id); 出站按平台键路由, 客户端才能按自己的键轮询到回复。适配器
    未提供平台键时 (OneBot 等按 group/user 路由的平台) 回退内部 session_id。
    R1-①: 扫描回复文本中的 ``artifact:<64位hex>`` 引用, 经 ArtifactStore.get_ref
    取元数据 + MediaResolver.resolve_for_channel 转 Channel segment append 到
    reply.segments (此前只发文本, 生成的图/语音发不出去)。MediaResolver 不支持的
    平台 (webchat/telegram/discord) 跳过 segment, 仅文本。
    """
    adapter = channel_registry.get(incoming.platform)
    if adapter is None:
        logger.warning("未找到对应平台适配器，无法发送回复", platform=incoming.platform, agent_id=agent_id)
        return

    reply = ISACMessage(
        msg_id="",  # 发送后由平台分配
        platform=incoming.platform,
        timestamp=0,
        user_id=incoming.user_id,
        user_name="",  # 发送方是 Bot，无需昵称
        group_id=incoming.group_id,
        session_id=platform_session_id or incoming.session_id,
        content=reply_text,
        reply_to=incoming.msg_id,
        # Fix-95: 透传 incoming.metadata —— qq_official send() 依赖
        # metadata["qq_official_source"]=="AT_MESSAGE_CREATE" 选频道端点
        # (/channels/{id}/messages); 此前出站不带 metadata, source 恒 "" → 频道
        # 回复落入群端点 (/v2/groups/{channel_id}/messages, channel_id 当
        # group_openid) → 100% 发送失败。其余平台不读该键, 透传无副作用。
        metadata=dict(incoming.metadata or {}),
    )
    # R1-①: 扫 artifact 引用转 segment (artifact_store 注入时)
    if artifact_store is not None:
        await _append_artifact_segments(reply, artifact_store, incoming.platform)
    success = await adapter.send(reply)
    if not success:
        logger.warning("回复发送失败", platform=incoming.platform, agent_id=agent_id)
    else:
        logger.info("Agent 回复已发送", agent_id=agent_id, platform=incoming.platform, length=len(reply_text))


async def _append_artifact_segments(reply: ISACMessage, artifact_store: Any, platform: str) -> None:
    """R1-①: 扫回复文本 artifact:<hex> → get_ref → MediaResolver 转 segment。

    逐引用异常隔离 (单个 artifact 解析失败不影响其余)。segment append 到 reply.segments。
    """
    import re

    from isac.channel.media_resolver import MediaResolver

    ids = re.findall(r"artifact:([a-f0-9]{64})", reply.content or "")
    seen: set[str] = set()
    for aid in ids:
        if aid in seen:
            continue
        seen.add(aid)
        try:
            ref = await artifact_store.get_ref(aid)
            if ref is None:
                continue
            segment = MediaResolver.resolve_for_channel(platform, ref)
            if segment is not None:
                reply.segments.append(segment)
        except Exception as exc:  # noqa: BLE001
            logger.warning("artifact 转 segment 失败, 跳过", artifact_id=aid, error=str(exc))


def _make_progress_sender(
    channel_registry: ChannelRegistry, incoming: ISACMessage, agent_id: str, platform_session_id: str = ""
) -> Callable[[str, ProgressEvent], Awaitable[None]]:
    """D9: 构造绑定到本次到达消息所属 Channel 的进度 sender。

    与 _send_reply 同构: 按 incoming.platform 找 adapter, 构造一条降级为普通文本的
    ISACMessage, 附 metadata.message_kind=progress 供 Channel 侧按需特殊处理
    (WebChat 输出原生 kind 字段, 其余平台按普通文本发送)。找不到 adapter / 发送失败
    时只记日志, 不得影响主任务 (进度是旁路信号)。
    Q0: 与 _send_reply 一致改用 platform_session_id (gateway 改写前的平台会话键)
    路由, WebChat 进度帧此前落在内部 sess_* 键下, 客户端同样轮询不到。
    """

    async def sender(text: str, event: ProgressEvent) -> None:
        adapter = channel_registry.get(incoming.platform)
        if adapter is None:
            return
        progress_message = ISACMessage(
            msg_id="",
            platform=incoming.platform,
            timestamp=0,
            user_id=incoming.user_id,
            user_name="",
            group_id=incoming.group_id,
            session_id=platform_session_id or incoming.session_id,
            content=text,
            reply_to=incoming.msg_id,
            # Fix-95: 合并 incoming.metadata (含 qq_official_source 端点路由凭证),
            # 进度专属键覆盖在后; 否则 qq_official 频道进度帧同样走错端点。
            metadata={
                **(incoming.metadata or {}),
                "message_kind": "progress",
                "task_id": event.task_id,
                "progress_stage": event.stage,
            },
        )
        try:
            await adapter.send(progress_message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("进度通知发送失败, 已忽略", platform=incoming.platform, agent_id=agent_id, error=str(exc))

    return sender
