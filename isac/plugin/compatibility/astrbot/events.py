"""AstrBot EventType 映射 (SPECIFICATION.md 2.7)。

消息事件 → EventBus；LLM 事件 → AgentHooks (不经过 EventBus)。
"""

from __future__ import annotations

from isac.core.events import AgentHookPoint, EventType


class AstrBotEventType:
    """兼容 astrbot.api.event.EventType (常量名与 AstrBot 对齐)"""

    OnMessageEvent = "on_message"
    OnAstrBotLoadedEvent = "on_astrbot_loaded"
    OnDecoratingResultEvent = "on_decorating_result"
    OnAfterSendMessage = "on_after_send"
    OnBeforeMessageEvent = "on_before_message"
    OnAfterMessageEvent = "on_after_message"
    OnLLMRequestEvent = "on_llm_request"
    OnAfterLLMResponseEvent = "on_after_llm_response"


# AstrBot 事件 → ISAC 事件/钩子映射表
ASTRBOT_EVENT_MAPPING: dict[str, EventType | AgentHookPoint] = {
    "on_message": EventType.ON_MESSAGE,
    "on_before_message": EventType.ON_MESSAGE_PRE,
    "on_after_message": EventType.POST_MESSAGE,
    "on_after_send": EventType.POST_SEND,
    "on_llm_request": AgentHookPoint.PRE_LLM,
    "on_after_llm_response": AgentHookPoint.POST_LLM,
}
