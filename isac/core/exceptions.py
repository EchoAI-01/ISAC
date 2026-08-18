"""ISAC 结构化错误体系 (SPECIFICATION.md 5.3)。

错误处理模式 (重试/降级/隔离) 见 SPECIFICATION.md 5.1/5.2。
"""


class ISACError(Exception):
    """ISAC 基础错误"""

    code: str = "ISAC_ERROR"
    retriable: bool = False

    def __init__(self, message: str, *, context: dict | None = None, retriable: bool | None = None):
        super().__init__(message)
        self.message = message
        self.context = context
        # 允许构造时显式覆盖类级 retriable (默认沿用子类声明)
        if retriable is not None:
            self.retriable = retriable


class PlatformError(ISACError):
    """平台连接错误"""

    code = "PLATFORM_ERROR"
    retriable = True


class LLMError(ISACError):
    """LLM 调用错误"""

    code = "LLM_ERROR"
    retriable = True


class RateLimitError(LLMError):
    """LLM 限流错误 (可重试，触发指数退避)"""

    code = "RATE_LIMIT"
    retriable = True


class MemoryError(ISACError):
    """记忆系统错误"""

    code = "MEMORY_ERROR"
    retriable = False


class ToolError(ISACError):
    """工具执行错误"""

    code = "TOOL_ERROR"
    retriable = False


class RoutingError(ISACError):
    """路由错误 (如无匹配 Agent)"""

    code = "ROUTING_ERROR"
    retriable = False


class AgentNotFoundError(ISACError):
    """Agent 不存在"""

    code = "AGENT_NOT_FOUND"
    retriable = False


class InterAgentLinkDeniedError(ISACError):
    """Agent 互联被 ACL 拒绝"""

    code = "INTER_AGENT_DENIED"
    retriable = False


class InterAgentTimeoutError(ISACError):
    """Fix-111: Agent 互联投递超时 (bus.send 的 wait_for 到期)。

    此前 bus.send 无超时 —— 目标 Agent 处理挂起时, 发起方的 A2A 工具在 Loop 内
    无限等待 (占着会话锁与话轮)。超时后投递任务被取消, 发起方如实收到失败。
    """

    code = "INTER_AGENT_TIMEOUT"
    retriable = True


class InterAgentRecursionError(ISACError):
    """Fix-111: Agent 互联递归深度超限 (A 调 B、B 又调 A 的嵌套链过深)。

    此前无递归保护 —— 互调链 (A→B→A→B…) 每层是一次完整的 handle_message +
    Loop, 可无限嵌套耗尽资源。深度经 contextvar 沿投递链传播, 超限即拒绝。
    """

    code = "INTER_AGENT_RECURSION"
    retriable = False


class MediaValidationError(ISACError):
    """媒体输入校验失败 (路径越权 / 大小超限 / MIME 未知 / kind 不匹配)"""

    code = "MEDIA_VALIDATION_ERROR"
    retriable = False
