"""原生 SDK 插件钩子常量 (Native SDK v2 独有能力)。"""

from enum import Enum


class InterAgentHookPoint(Enum):
    """Agent 互联钩子点 (Native SDK v2)"""

    ON_INTER_AGENT_MESSAGE = "on_inter_agent_message"  # 收到互联消息时
    BEFORE_INTER_AGENT_SEND = "before_inter_agent_send"  # 发送互联消息前
