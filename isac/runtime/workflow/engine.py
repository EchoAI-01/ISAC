"""WorkflowEngine: 工作流编排引擎 (O3, ARCHITECTURE.md 工作流编排)。

O3 实现: register/start/step/resume 真实调度 (串行按 transitions 顺序, 并行用
asyncio.gather, 条件按 condition_evaluator 返回 SKIPPED, 重试 max_retries 次);
状态机 PENDING→RUNNING→SUCCEEDED/FAILED; resume 把 RUNNING 标为 FAILED
(中断后不续跑, 与 L5 一致); 持久化到 data/workflows/<id>.json (原子写)。
默认不启动后台调度; 无 action_handler 时 stage 视为 noop (零行为变化)。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING

from isac.runtime.workflow.models import (
    Stage,
    StageStatus,
    TransitionKind,
    Workflow,
    WorkflowStatus,
)
from isac.utils.fs import atomic_write_json
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = get_logger(__name__)

DEFAULT_BASE_DIR = "data/workflows"
DEFAULT_MAX_RETRIES = 3

# 动作处理器签名: (Stage) -> None (异常视为失败, 触发重试)
ActionHandler = Callable[[Stage], "Awaitable[None]"]
# 条件求值器签名: (condition_str) -> bool (True=执行, False=跳过 SKIPPED)
ConditionEvaluator = Callable[[str], bool]


class WorkflowEngine:
    """工作流引擎 (登记 + 生命周期 + 串/并/条件/重试调度)。"""

    def __init__(self, *, base_dir: str = DEFAULT_BASE_DIR) -> None:
        self._workflows: dict[str, Workflow] = {}
        self._base_dir = base_dir
        self._action_handler: ActionHandler | None = None
        self._condition_evaluator: ConditionEvaluator | None = None

    def set_action_handler(self, handler: ActionHandler) -> None:
        """注入 stage 动作处理器 (供测试/生产接线)."""
        self._action_handler = handler

    def set_condition_evaluator(self, evaluator: ConditionEvaluator) -> None:
        """注入条件求值器 (kind=conditional 时调用)."""
        self._condition_evaluator = evaluator

    def register(self, workflow: Workflow) -> None:
        """登记一个工作流定义 (重名覆盖)."""
        self._workflows[workflow.workflow_id] = workflow
        logger.debug("工作流已登记", workflow_id=workflow.workflow_id)

    def get(self, workflow_id: str) -> Workflow | None:
        return self._workflows.get(workflow_id)

    async def start(self, workflow_id: str) -> WorkflowStatus:
        """启动一个已登记的工作流 (按 transitions 调度 stages)."""
        wf = self._workflows.get(workflow_id)
        if wf is None:
            return WorkflowStatus.FAILED
        wf.status = WorkflowStatus.RUNNING
        self._persist(wf)
        try:
            await self._run_workflow(wf)
        except Exception as exc:  # noqa: BLE001
            logger.warning("工作流执行失败", workflow_id=workflow_id, error=str(exc))
            wf.status = WorkflowStatus.FAILED
            self._persist(wf)
            return WorkflowStatus.FAILED
        self._persist(wf)
        return wf.status

    async def _run_workflow(self, wf: Workflow) -> None:
        """按 transitions 调度 stages; 失败抛异常让上层标 FAILED."""
        # 找入口 stage (无 incoming transition 的第一个 stage)
        incoming = {t.to_stage for t in wf.transitions}
        entry_stages = [s for s in wf.stages if s.stage_id not in incoming] or wf.stages[:1]
        if not entry_stages:
            wf.status = WorkflowStatus.SUCCEEDED
            return
        # 按串行默认跑入口 stage, transitions 决定后续
        executed: set[str] = set()
        await self._run_stage_chain(wf, entry_stages[0], executed)
        wf.status = WorkflowStatus.SUCCEEDED

    async def _run_stage_chain(
        self, wf: Workflow, stage: Stage, executed: set[str]
    ) -> None:
        """递归执行 stage 链 (按 transitions 串行/并行/条件/重试)."""
        if stage.stage_id in executed:
            return
        executed.add(stage.stage_id)
        await self._execute_stage(wf, stage)
        # 找出从本 stage 出发的 transitions
        outgoing = [t for t in wf.transitions if t.from_stage == stage.stage_id]
        if not outgoing:
            return
        # 按 kind 分组
        parallel_targets: list[Stage] = []
        for t in outgoing:
            target = next((s for s in wf.stages if s.stage_id == t.to_stage), None)
            if target is None:
                continue
            if t.kind is TransitionKind.CONDITIONAL:
                if self._evaluate(t.condition):
                    await self._run_stage_chain(wf, target, executed)
                else:
                    target.status = StageStatus.SKIPPED
            elif t.kind is TransitionKind.PARALLEL:
                parallel_targets.append(target)
            elif t.kind is TransitionKind.RETRY:
                # retry 在 _execute_stage 内处理, 不递归
                pass
            else:  # SEQUENTIAL
                await self._run_stage_chain(wf, target, executed)
        if parallel_targets:
            await asyncio.gather(*[self._run_stage_chain(wf, t, executed) for t in parallel_targets])

    async def _execute_stage(self, wf: Workflow, stage: Stage) -> None:
        """执行单个 stage (含重试逻辑)."""
        stage.status = StageStatus.RUNNING
        # 找 retry transition 决定 max_retries
        retry_transitions = [
            t
            for t in wf.transitions
            if t.from_stage == stage.stage_id and t.kind is TransitionKind.RETRY
        ]
        max_retries = DEFAULT_MAX_RETRIES if retry_transitions else 1
        attempts = 0
        while attempts < max_retries:
            attempts += 1
            try:
                if self._action_handler is not None:
                    await self._action_handler(stage)
                stage.status = StageStatus.SUCCEEDED
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "stage 执行失败, 尝试重试",
                    workflow_id=wf.workflow_id,
                    stage_id=stage.stage_id,
                    attempt=attempts,
                    max=max_retries,
                    error=str(exc),
                )
                if attempts >= max_retries:
                    stage.status = StageStatus.FAILED
                    raise
        stage.status = StageStatus.FAILED

    def _evaluate(self, condition: str) -> bool:
        """求值条件表达式 (默认 False; 注入 evaluator 时委托)."""
        if self._condition_evaluator is None:
            return not condition or condition.lower() in ("true", "1", "yes")
        try:
            return self._condition_evaluator(condition)
        except Exception:  # noqa: BLE001
            return False

    async def step(self, workflow_id: str) -> WorkflowStatus:
        """推进工作流一步 (执行下一个 PENDING stage)."""
        wf = self._workflows.get(workflow_id)
        if wf is None:
            return WorkflowStatus.FAILED
        if wf.status is WorkflowStatus.SUCCEEDED:
            return wf.status
        wf.status = WorkflowStatus.RUNNING
        next_stage = next((s for s in wf.stages if s.status is StageStatus.PENDING), None)
        if next_stage is None:
            wf.status = WorkflowStatus.SUCCEEDED
            self._persist(wf)
            return wf.status
        try:
            await self._execute_stage(wf, next_stage)
        except Exception as exc:  # noqa: BLE001
            logger.warning("step 执行失败", workflow_id=workflow_id, error=str(exc))
            wf.status = WorkflowStatus.FAILED
            self._persist(wf)
            return WorkflowStatus.FAILED
        # 检查是否还有 PENDING
        has_pending = any(s.status is StageStatus.PENDING for s in wf.stages)
        wf.status = WorkflowStatus.SUCCEEDED if not has_pending else WorkflowStatus.RUNNING
        self._persist(wf)
        return wf.status

    async def resume(self, workflow_id: str) -> WorkflowStatus:
        """重启后从持久化断点恢复 (与 L5 一致: RUNNING 标为 FAILED, 不续跑)."""
        wf = self._workflows.get(workflow_id)
        if wf is None:
            return WorkflowStatus.FAILED
        if wf.status is WorkflowStatus.RUNNING:
            logger.info("工作流中断后恢复, 标为 FAILED (不续跑)", workflow_id=workflow_id)
            wf.status = WorkflowStatus.FAILED
            self._persist(wf)
        return wf.status

    def _persist(self, wf: Workflow) -> None:
        """原子写 JSON 到 data/workflows/<id>.json."""
        try:
            path = Path(self._base_dir) / f"{wf.workflow_id}.json"
            data = {
                "workflow_id": wf.workflow_id,
                "name": wf.name,
                "status": wf.status.value,
                "stages": [
                    {
                        "stage_id": s.stage_id,
                        "action": s.action,
                        "status": s.status.value,
                    }
                    for s in wf.stages
                ],
                "metadata": dict(wf.metadata),
            }
            atomic_write_json(path, data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("工作流持久化失败, 已忽略", workflow_id=wf.workflow_id, error=str(exc))


# 避免未使用 import 警告
_ = (json, Coroutine)
