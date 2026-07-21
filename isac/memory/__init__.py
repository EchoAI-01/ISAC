"""Memory System: 存储、检索、注入策略 (ARCHITECTURE.md 3.6)。

职责边界 (DEVELOP.md 1.1): 不直接调用 LLM (启发式记忆经注入策略例外)。
所有记忆表带 agent_id 命名空间 ("shared" = 跨 Agent 共享)。
"""
