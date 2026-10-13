"""L1 (2026-10-13 review): Channel 交互工具服务构建器。

背景: 5 个 Channel 交互工具 (send_emoji / send_image / fetch_history /
switch_chat / view_forward_message) 自 H 阶段注册起, 其依赖的服务键
(channel_send / channel_history / session_topic / channel_forward) 全仓
**零生产注入** —— 工具在 LLM schema 可见 (默认 allow) 但调用恒失败, LLM 反复
调用死工具 (与 Q0 对 web_search 的定性同款病灶)。本模块提供真实后端闭包,
由 runtime/assembly 在 per-Agent services 装配时注入 (不入全局袋 —— 全局键数
已顶红线 36, 且 channel_history 需要 agent 维度的会话键, 本就是 per-Agent 语义)。

覆盖与不覆盖:
- channel_send: 经 ChannelRegistry 按平台路由发送 (send_emoji / send_image 用);
- channel_history: 从 U1 事件流读当前会话最近内容事件 (跨平台统一口径);
- channel_forward: 合并转发内容读取 (OneBot 11 get_forward_msg, 适配器实现
  fetch_forward 后经 registry 能力发现, 不硬编码平台名);
- session_topic: **不提供** —— 话题机制当前无任何存储/消费方 (全仓零读取),
  接线即"写死数据"反面教材; switch_chat 默认档位降为 deny, 待话题消费方
  落地后再开 (Q0 口径)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.channel.model import ISACMessage

logger = get_logger(__name__)


@dataclass
class ChannelHistoryMessage:
    """历史/转发消息的轻量视图 (fetch_history / view_forward_message 工具格式化用)。

    只暴露工具需要的三个字段, 不把平台原始事件对象透传进 agent 层。
    """

    user_id: str = ""
    user_name: str = ""
    content: str = ""


def build_channel_send(registry: Any) -> Any:
    """构造 channel_send 服务: ``await sender(reply: ISACMessage) -> bool``。

    按回复自身 platform 从 registry 取适配器发送; 无 registry / 无适配器 /
    适配器异常一律返回 False (调用方工具向 LLM 报告失败, 不静默)。
    """
    if registry is None:
        return None

    async def channel_send(reply: ISACMessage) -> bool:
        adapter = registry.get(reply.platform) if hasattr(registry, "get") else None
        if adapter is None:
            logger.warning("channel_send: 无平台适配器", platform=reply.platform)
            return False
        try:
            return bool(await adapter.send(reply))
        except Exception as exc:  # noqa: BLE001 适配器异常按失败上报
            logger.warning("channel_send: 适配器发送异常", platform=reply.platform, error=str(exc))
            return False

    return channel_send


def build_session_history_fetcher(store: Any, agent_id: str) -> Any:
    """构造 channel_history 服务: ``await fetcher(incoming, limit=N) -> list``。

    从 U1 事件流 (session_event_store) 读当前会话的最近**内容**事件
    (message.user / turn.completed), 跨平台统一口径 —— 平台原生历史 API 各家
    语义不一且部分平台无开放接口, 事件流本就是会话历史的唯一事实源。
    会话键派生与 manager 写侧同源 (gateway.session.session_key_for)。
    """
    if store is None:
        return None

    async def channel_history(incoming: ISACMessage, *, limit: int = 20) -> list[ChannelHistoryMessage]:
        from isac.gateway.session import session_key_for
        from isac.session.models import EVENT_TURN_COMPLETED, EVENT_USER_MESSAGE

        key = session_key_for(
            agent_id, incoming.platform, incoming.user_id, incoming.group_id
        )
        n = max(1, min(int(limit), 100))
        # 工具密集会话中内容事件可能被 tool.* 稀释 —— 采样窗口放大到 4 倍,
        # 过滤后取**最近** n 条 (而非窗口内最旧的 n 条)。
        events = await store.fetch_recent(key, limit=n * 4)
        out: list[ChannelHistoryMessage] = []
        for e in events:
            if e.event_type == EVENT_USER_MESSAGE:
                out.append(
                    ChannelHistoryMessage(
                        user_id=str(e.payload.get("user_id", "") or ""),
                        user_name=str(e.payload.get("user_name", "") or ""),
                        content=str(e.payload.get("content", "") or ""),
                    )
                )
            elif e.event_type == EVENT_TURN_COMPLETED:
                out.append(ChannelHistoryMessage(content=str(e.payload.get("content", "") or "")))
        return out[-n:]

    return channel_history


def build_channel_forward(registry: Any) -> Any:
    """构造 channel_forward 服务: ``await fetcher(forward_id) -> list``。

    合并转发内容读取按**适配器能力发现**: 遍历 registry 中实现了
    ``fetch_forward(forward_id)`` 的适配器 (当前仅 OneBot, QQ 合并转发是
    该工具的存在动机), 不按平台名硬编码 —— 新平台适配器实现同名方法即自动
    纳入。无任何适配器支持时返回空列表 (工具向 LLM 报"当前平台不支持")。
    """
    if registry is None:
        return None

    async def channel_forward(forward_id: str) -> list[ChannelHistoryMessage]:
        adapters = registry.list() if hasattr(registry, "list") else []
        for adapter in adapters:
            fetch = getattr(adapter, "fetch_forward", None)
            if fetch is None:
                continue
            try:
                return list(await fetch(forward_id))
            except Exception as exc:  # noqa: BLE001 单适配器失败继续试下一个
                logger.warning(
                    "channel_forward: 适配器读取转发失败",
                    adapter=getattr(adapter, "platform_name", "?"),
                    error=str(exc),
                )
        return []

    return channel_forward
