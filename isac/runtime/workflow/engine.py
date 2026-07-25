"""WorkflowEngine: 工作流编排引擎骨架 (O3)。

[框架已搭建 / scaffolding] register/start/step/resume 挂接点就位;真正的串/并/条件/重试
调度、跨 Agent/工具步骤执行、可观测与断点恢复留待 O3 实现节点 (见 TODO)。默认不启动
后台调度, 零行为变化。
"""

from __future__ import annotations

from isac.runtime.workflow.models import Workflow, WorkflowStatus
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class WorkflowEngine:
    """工作流引擎骨架 (登记 + 生命周期挂接点)。"""

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}

    def register(self, workflow: Workflow) -> None:
        """登记一个工作流定义 (重名覆盖)。"""
        self._workflows[workflow.workflow_id] = workflow
        logger.debug("工作流已登记", workflow_id=workflow.workflow_id)

    def get(self, workflow_id: str) -> Workflow | None:
        return self._workflows.get(workflow_id)

    async def start(self, workflow_id: str) -> WorkflowStatus:
        """启动一个已登记的工作流。

        TODO(O3): 按 transitions 调度 stages (串/并/条件/重试), 驱动状态机;
        骨架阶段仅返回当前状态 (PENDING), 不真正执行。
        """
        wf = self._workflows.get(workflow_id)
        if wf is None:
            return WorkflowStatus.FAILED
        return wf.status  # 骨架: 不推进, 保持 PENDING

    async def step(self, workflow_id: str) -> WorkflowStatus:
        """推进工作流一步。TODO(O3): 执行下一个就绪 stage; 骨架 no-op 返回当前状态。"""
        wf = self._workflows.get(workflow_id)
        return wf.status if wf else WorkflowStatus.FAILED

    async def resume(self, workflow_id: str) -> WorkflowStatus:
        """重启后从持久化断点恢复。TODO(O3): 与 K4/L5 一致的恢复策略; 骨架 no-op。"""
        wf = self._workflows.get(workflow_id)
        return wf.status if wf else WorkflowStatus.FAILED
