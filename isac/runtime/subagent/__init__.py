"""J4 SubAgent Runtime 子系统 (SPECIFICATION.md 2.5 / ROUTING_AND_AGENT_MESH.md)。

每个 Agent 可用 delegate_task 创建隔离子任务; 子 Agent 使用独立 History/Prompt/Budget/
Workspace 和父权限子集。主 Agent 默认只收到结构化 ``SubAgentResult``、证据引用和用量
摘要, 完整脱敏日志按 task_id 显式查询。

骨架状态: 数据契约 + Supervisor/Journal/ContextEnvelope/Broker 接口就位; 真实子 Agent
执行循环、恢复/取消传播、H3 TaskRunner 迁移留待 J4 实现节点。
"""

from __future__ import annotations

from isac.runtime.subagent.broker import SubAgentResultBroker
from isac.runtime.subagent.context import ContextEnvelopeBuilder
from isac.runtime.subagent.journal import SubAgentJournal
from isac.runtime.subagent.models import (
    ContextEnvelope,
    SubAgentEvent,
    SubAgentPolicy,
    SubAgentResult,
    SubAgentRun,
    SubAgentTask,
)
from isac.runtime.subagent.supervisor import SubAgentSupervisor

__all__ = [
    "ContextEnvelope",
    "ContextEnvelopeBuilder",
    "SubAgentEvent",
    "SubAgentJournal",
    "SubAgentPolicy",
    "SubAgentResult",
    "SubAgentResultBroker",
    "SubAgentRun",
    "SubAgentSupervisor",
    "SubAgentTask",
]
