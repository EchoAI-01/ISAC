"""ISAC 事件枚举 (SPECIFICATION.md 4.1)。

EventBus 事件 (Intercept + Async 双层) 与 Agent Loop 内部钩子点分离。
"""

from enum import Enum


class EventType(Enum):
    """ISAC 事件类型（由 EventBus 处理）"""

    # 生命周期
    ON_START = "on_start"  # 系统启动
    ON_STOP = "on_stop"  # 系统停止
    ON_SESSION_CREATE = "on_session_create"  # 会话创建
    ON_SESSION_CLOSE = "on_session_close"  # 会话关闭

    # 消息事件
    ON_MESSAGE_PRE = "on_message_pre"  # 消息预处理 (Intercept)
    ON_MESSAGE = "on_message"  # 消息到达 (Intercept)
    POST_MESSAGE = "post_message"  # 消息处理完成 (Async)

    # 发送事件
    POST_SEND_PRE = "post_send_pre"  # 发送前预处理 (Intercept)
    POST_SEND = "post_send"  # 发送完成 (Async)

    # 记忆事件
    ON_MEMORY_RETRIEVE = "on_memory_retrieve"  # 记忆检索
    ON_MEMORY_STORE = "on_memory_store"  # 记忆存储


class AgentHookPoint(Enum):
    """Agent Loop 内部钩子点（不经过 EventBus，直接在 Agent Loop 内部触发）"""

    PRE_LLM = "pre_llm"  # LLM 调用前，可修改 messages
    POST_LLM = "post_llm"  # LLM 响应后，可处理 response
    PRE_TOOL = "pre_tool"  # 工具调用前，返回 False 可阻止
    POST_TOOL = "post_tool"  # 工具调用后，可触发副作用
    COMPRESS = "compress"  # 上下文过大时触发
    FINAL_RESPONSE = "final_response"  # 最终回复前
