"""ISAC 结构化错误体系 (SPECIFICATION.md 5.3)。

错误处理模式 (重试/降级/隔离) 见 SPECIFICATION.md 5.1/5.2。
"""


class ISACError(Exception):
    """ISAC 基础错误"""

    code: str = "ISAC_ERROR"
    retriable: bool = False

    def __init__(self, message: str, *, context: dict | None = None):
        super().__init__(message)
        self.message = message
        self.context = context


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
