"""控制面: Admin REST API / ISAC MCP Server / Webhooks (ARCHITECTURE.md 3.9)。

职责边界 (DEVELOP.md 1.1): 不处理消息数据面逻辑；
所有操作复用 AgentManager/Router/Bus 公开方法，不复制业务逻辑。
"""
