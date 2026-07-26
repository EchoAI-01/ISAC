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
from typing import TYPE_CHECKING, Any

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
        """按 transitions 调度 stages; 失败抛异常让上层标 FAILED。

        CR3-M7 重写:
        - 启动全部入口节点 (此前只启动 entry_stages[0], 多入口根节点被丢弃却仍标
          SUCCEEDED); 入口判定与入度计算都排除 RETRY 边 (RETRY 是 stage 的重试
          配置自环, 不是流转边, 计入会让带重试的入口 stage 被误判为"有父节点")。
        - fan-in (汇合) 节点按入度计数, 等所有父边都被满足 (父 stage 完成或被
          跳过) 才执行 (此前 `if stage_id in executed` 使汇合节点在首个父分支
          到达时就提前运行, 钻石 DAG 下 D 在 C 完成前就跑)。
        - conditional 为假时目标标 SKIPPED; 被跳过的 stage 同样"满足"其下游
          依赖 (否则含条件分支的汇合节点会永远等不到), 但只有至少一个父 stage
          真正 SUCCEEDED 的节点才会执行 —— 全部父分支都被跳过的节点级联 SKIPPED。
        - 入度只统计"运行期可能被满足"的边 (CR3 复核修正): 悬空边 (from/to 不是
          真实 stage)、非 RETRY 自环、以及从入口 DFS 分类出的回环边 (back edge)
          与不可达来源边都被排除 —— 否则这些永远等不到的父边会让目标 stage
          静默卡在 PENDING, 工作流却报 SUCCEEDED。回环边运行期不再传播 (目标
          必然已执行, 与旧实现 executed 集合防重入的效果一致)。
        - 收尾对残留 PENDING (从入口不可达的 stage, 如游离环) 记 warning, 与旧
          实现"不可达即不执行"的行为一致但不再无声。
        """
        stages_by_id = {s.stage_id: s for s in wf.stages}
        entry_stages, effective_transitions, in_degree = self._plan_schedule(wf, stages_by_id)
        if not entry_stages:
            wf.status = WorkflowStatus.SUCCEEDED
            return
        executed: set[str] = set()
        # succeeded_parents: 记录哪些节点至少有一个父 stage 真正执行成功
        # (入口节点无父, 视为可执行)。
        succeeded_parents: set[str] = {s.stage_id for s in entry_stages}
        await asyncio.gather(
            *[
                self._advance(wf, stage, in_degree, stages_by_id, effective_transitions, executed, succeeded_parents)
                for stage in entry_stages
            ]
        )
        pending_left = [s.stage_id for s in wf.stages if s.status is StageStatus.PENDING]
        if pending_left:
            logger.warning(
                "部分 stage 从入口不可达, 未被调度 (保持 PENDING)",
                workflow_id=wf.workflow_id,
                stages=pending_left,
            )
        wf.status = WorkflowStatus.SUCCEEDED

    def _plan_schedule(
        self, wf: Workflow, stages_by_id: dict[str, Stage]
    ) -> tuple[list[Stage], list, dict[str, int]]:
        """图预处理 (CR3-M7): 过滤无效边 → 判定入口 → 排除回环/不可达边 → 计算入度。

        返回 (entry_stages, effective_transitions, in_degree)。effective 边保证:
        from/to 都是真实 stage、非自环、来源从入口可达、且不是 DFS 回环边 ——
        因此每条边在运行期都必然被满足一次, 入度归零可达成。
        """
        flow: list = []
        for t in wf.transitions:
            if t.kind is TransitionKind.RETRY:
                continue
            if t.from_stage not in stages_by_id or t.to_stage not in stages_by_id:
                logger.warning(
                    "忽略指向/来自不存在 stage 的流转边",
                    workflow_id=wf.workflow_id, from_stage=t.from_stage, to_stage=t.to_stage,
                )
                continue
            if t.from_stage == t.to_stage:
                logger.warning(
                    "忽略非 RETRY 自环边 (重试语义请用 kind=RETRY)",
                    workflow_id=wf.workflow_id, stage_id=t.from_stage,
                )
                continue
            flow.append(t)
        raw_in: dict[str, int] = {}
        for t in flow:
            raw_in[t.to_stage] = raw_in.get(t.to_stage, 0) + 1
        entry_stages = [s for s in wf.stages if raw_in.get(s.stage_id, 0) == 0]
        if not entry_stages and wf.stages:
            # 全部 stage 都有入边 (整体成环); 退回旧行为从首个 stage 起跑
            entry_stages = wf.stages[:1]
        reachable, back_edge_ids = self._classify_edges(entry_stages, flow)
        effective = [t for t in flow if id(t) not in back_edge_ids and t.from_stage in reachable]
        in_degree: dict[str, int] = {}
        for t in effective:
            in_degree[t.to_stage] = in_degree.get(t.to_stage, 0) + 1
        return entry_stages, effective, in_degree

    @staticmethod
    def _classify_edges(entry_stages: list[Stage], flow: list) -> tuple[set[str], set[int]]:
        """从入口做迭代 DFS: 返回 (可达 stage 集合, 回环边 id 集合)。

        回环边 = 指向当前 DFS 栈上节点的边 (灰色节点), 是让图成环的边;
        把它们从入度中排除后, 剩余 effective 边构成可达子图上的 DAG。
        """
        adjacency: dict[str, list] = {}
        for t in flow:
            adjacency.setdefault(t.from_stage, []).append(t)
        color: dict[str, int] = {}  # 缺失=white, 1=gray(栈上), 2=black(完成)
        reachable: set[str] = set()
        back_edge_ids: set[int] = set()
        for entry in entry_stages:
            if color.get(entry.stage_id, 0) != 0:
                continue
            stack: list[tuple[str, Any]] = [(entry.stage_id, iter(adjacency.get(entry.stage_id, [])))]
            color[entry.stage_id] = 1
            reachable.add(entry.stage_id)
            while stack:
                node_id, edge_iter = stack[-1]
                pushed = False
                for edge in edge_iter:
                    target_color = color.get(edge.to_stage, 0)
                    if target_color == 1:
                        back_edge_ids.add(id(edge))
                    elif target_color == 0:
                        color[edge.to_stage] = 1
                        reachable.add(edge.to_stage)
                        stack.append((edge.to_stage, iter(adjacency.get(edge.to_stage, []))))
                        pushed = True
                        break
                if not pushed:
                    color[node_id] = 2
                    stack.pop()
        return reachable, back_edge_ids

    async def _advance(  # noqa: C901 - 调度核心: 串/并/条件/汇合语义集中于此
        self,
        wf: Workflow,
        stage: Stage,
        in_degree: dict[str, int],
        stages_by_id: dict[str, Stage],
        flow_transitions: list,
        executed: set[str],
        succeeded_parents: set[str],
    ) -> None:
        """执行 stage 并传播其下游依赖 (fan-in 按入度等全部父边满足)。"""
        if stage.stage_id in executed:
            return
        executed.add(stage.stage_id)
        skipped = stage.status is StageStatus.SKIPPED
        if not skipped:
            await self._execute_stage(wf, stage)
        # 传播: 本 stage (完成或被跳过) 满足每条出边; 目标入度归零时才可推进。
        sequential_ready: list[Stage] = []
        parallel_ready: list[Stage] = []
        for t in flow_transitions:
            if t.from_stage != stage.stage_id:
                continue
            target = stages_by_id.get(t.to_stage)
            if target is None or target.stage_id in executed:
                continue
            edge_satisfies_execution = not skipped
            if t.kind is TransitionKind.CONDITIONAL:
                if skipped or not self._evaluate(t.condition):
                    # 条件为假 (或父分支已被跳过): 目标不因这条边而执行
                    edge_satisfies_execution = False
            if edge_satisfies_execution:
                succeeded_parents.add(target.stage_id)
            in_degree[target.stage_id] = in_degree.get(target.stage_id, 1) - 1
            if in_degree[target.stage_id] > 0:
                continue  # 还有父边未满足 (fan-in 等待)
            if target.stage_id not in succeeded_parents:
                # 所有父分支都被跳过/条件为假: 级联标 SKIPPED, 但仍要传播其下游
                target.status = StageStatus.SKIPPED
            if t.kind is TransitionKind.PARALLEL:
                parallel_ready.append(target)
            else:
                sequential_ready.append(target)
        for target in sequential_ready:
            await self._advance(wf, target, in_degree, stages_by_id, flow_transitions, executed, succeeded_parents)
        if parallel_ready:
            await asyncio.gather(
                *[
                    self._advance(wf, target, in_degree, stages_by_id, flow_transitions, executed, succeeded_parents)
                    for target in parallel_ready
                ]
            )

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
