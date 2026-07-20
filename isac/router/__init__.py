"""Message Router: 决定消息归属哪个 Agent (ARCHITECTURE.md 3.2)。

职责边界 (DEVELOP.md 1.1): 不处理 LLM 调用、不操作记忆。
只依赖 utils/ (路由规则是纯数据 + 匹配逻辑)。
"""
