"""Workflow 编排数据契约 (O3)。

声明式多步骤编排的值对象: 工作流、阶段、转移。纯数据、不含行为; 执行在 engine.py。

[框架已搭建 / scaffolding] 契约就位; 真实的串/并/条件/重试执行、跨 Agent/工具步骤、
可观测与恢复留待 O3 实现节点。默认不启动引擎, 零行为变化。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class WorkflowStatus(StrEnum):
    """工作流实例状态 (O3)。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageStatus(StrEnum):
    """单个阶段状态 (O3)。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class TransitionKind(StrEnum):
    """阶段间转移类型 (O3)。"""

    SEQUENTIAL = "sequential"  # 串行
    PARALLEL = "parallel"  # 并行
    CONDITIONAL = "conditional"  # 条件
    RETRY = "retry"  # 重试


@dataclass
class Stage:
    """工作流中的一个步骤 (可跨 Agent/工具)。"""

    stage_id: str
    action: str  # 待执行动作标识 (工具名 / Agent 动作 / 子工作流)
    params: dict = field(default_factory=dict)
    status: StageStatus = StageStatus.PENDING


@dataclass
class Transition:
    """阶段间的转移边。"""

    from_stage: str
    to_stage: str
    kind: TransitionKind = TransitionKind.SEQUENTIAL
    condition: str = ""  # kind=conditional 时的判定表达式 (O3 定义 DSL)


@dataclass
class Workflow:
    """一个声明式工作流定义 + 运行态。"""

    workflow_id: str
    name: str = ""
    stages: list[Stage] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    status: WorkflowStatus = WorkflowStatus.PENDING
    metadata: dict = field(default_factory=dict)
