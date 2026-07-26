"""O3 Workflow 编排引擎业务测试。

覆盖:
- start 推进状态机 PENDING → RUNNING → SUCCEEDED
- 串行 stages 按顺序执行
- 并行 stages 用 asyncio.gather
- 条件 stage 按条件跳过 (SKIPPED)
- 重试 stage 失败后重试 N 次
- resume 重启后标为 INTERRUPTED 不续跑 (与 L5 一致)
- step 推进单个 stage
- 持久化文件存在
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from isac.runtime.workflow.engine import WorkflowEngine
from isac.runtime.workflow.models import (
    Stage,
    StageStatus,
    Transition,
    TransitionKind,
    Workflow,
    WorkflowStatus,
)


def _make_workflow(
    workflow_id: str = "w1",
    stages: list[Stage] | None = None,
    transitions: list[Transition] | None = None,
) -> Workflow:
    return Workflow(
        workflow_id=workflow_id,
        name="test",
        stages=stages or [],
        transitions=transitions or [],
    )


@pytest.fixture
async def engine(tmp_path: Path) -> WorkflowEngine:
    """构造带持久化目录的 WorkflowEngine fixture."""
    eng = WorkflowEngine(base_dir=str(tmp_path))
    yield eng


# ── start 状态机 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_pending_to_running_to_succeeded(engine: WorkflowEngine) -> None:
    """无 transitions 的单 stage workflow: start 后直接 SUCCEEDED."""
    wf = _make_workflow(stages=[Stage(stage_id="s1", action="noop")])
    engine.register(wf)
    status = await engine.start("w1")
    assert status is WorkflowStatus.SUCCEEDED
    assert engine.get("w1").status is WorkflowStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_start_unknown_workflow_returns_failed(engine: WorkflowEngine) -> None:
    """未登记的 workflow_id 返回 FAILED."""
    status = await engine.start("nonexistent")
    assert status is WorkflowStatus.FAILED


# ── 串行 stages ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_sequential_stages_run_in_order(engine: WorkflowEngine) -> None:
    """串行 stages 按 transitions 顺序执行."""
    execution_order: list[str] = []

    async def action_handler(stage: Stage) -> None:
        execution_order.append(stage.stage_id)

    engine.set_action_handler(action_handler)
    wf = _make_workflow(
        stages=[Stage(stage_id="s1", action="a"), Stage(stage_id="s2", action="b"), Stage(stage_id="s3", action="c")],
        transitions=[
            Transition(from_stage="s1", to_stage="s2", kind=TransitionKind.SEQUENTIAL),
            Transition(from_stage="s2", to_stage="s3", kind=TransitionKind.SEQUENTIAL),
        ],
    )
    engine.register(wf)
    status = await engine.start("w1")
    assert status is WorkflowStatus.SUCCEEDED
    assert execution_order == ["s1", "s2", "s3"]


# ── 并行 stages ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_parallel_stages_run_concurrently(engine: WorkflowEngine) -> None:
    """并行 stages 用 asyncio.gather 同时执行."""
    started: list[float] = []
    finished: list[float] = []

    async def action_handler(stage: Stage) -> None:
        started.append(asyncio.get_event_loop().time())
        await asyncio.sleep(0.05)  # 模拟耗时
        finished.append(asyncio.get_event_loop().time())

    engine.set_action_handler(action_handler)
    wf = _make_workflow(
        stages=[Stage(stage_id="s1", action="a"), Stage(stage_id="s2", action="b")],
        transitions=[Transition(from_stage="s1", to_stage="s2", kind=TransitionKind.PARALLEL)],
    )
    engine.register(wf)
    await engine.start("w1")
    # 并行: s2 在 s1 完成前启动 (started 间隔 < sleep 时长 0.1, 留余量)
    assert len(started) == 2
    assert abs(started[1] - started[0]) < 0.1


# ── 条件 stage ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_conditional_stage_skipped_when_condition_false(engine: WorkflowEngine) -> None:
    """条件 stage 在 condition 返回 False 时标 SKIPPED, 不执行."""
    executed: list[str] = []

    async def action_handler(stage: Stage) -> None:
        executed.append(stage.stage_id)

    engine.set_action_handler(action_handler)
    engine.set_condition_evaluator(lambda condition_str: condition_str == "True")
    wf = _make_workflow(
        stages=[Stage(stage_id="s1", action="a"), Stage(stage_id="s2", action="b")],
        transitions=[
            Transition(from_stage="s1", to_stage="s2", kind=TransitionKind.CONDITIONAL, condition="False"),
        ],
    )
    engine.register(wf)
    await engine.start("w1")
    assert executed == ["s1"]  # s2 被跳过
    s2 = next(s for s in engine.get("w1").stages if s.stage_id == "s2")
    assert s2.status is StageStatus.SKIPPED


# ── 重试 stage ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_retry_stage_retries_on_failure(engine: WorkflowEngine) -> None:
    """重试 stage 失败后重试 max_retries 次; 仍失败则 workflow FAILED."""
    attempt_count = 0

    async def action_handler(stage: Stage) -> None:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:  # 前两次失败, 第三次成功
            raise RuntimeError("simulated failure")

    engine.set_action_handler(action_handler)
    wf = _make_workflow(
        stages=[Stage(stage_id="s1", action="flaky")],
        transitions=[Transition(from_stage="s1", to_stage="s1", kind=TransitionKind.RETRY)],
    )
    engine.register(wf)
    status = await engine.start("w1")
    # 重试 3 次后成功 (默认 max_retries=3)
    assert status is WorkflowStatus.SUCCEEDED
    assert attempt_count == 3


@pytest.mark.asyncio
async def test_start_retry_stage_fails_after_max_retries(engine: WorkflowEngine) -> None:
    """重试超过 max_retries 仍失败 → workflow FAILED."""
    async def action_handler(stage: Stage) -> None:
        raise RuntimeError("always fails")

    engine.set_action_handler(action_handler)
    wf = _make_workflow(
        stages=[Stage(stage_id="s1", action="always_fail")],
        transitions=[Transition(from_stage="s1", to_stage="s1", kind=TransitionKind.RETRY)],
    )
    engine.register(wf)
    status = await engine.start("w1")
    assert status is WorkflowStatus.FAILED


# ── step 推进单个 stage ────────────────────────────────────────


@pytest.mark.asyncio
async def test_step_advances_one_stage_at_a_time(engine: WorkflowEngine) -> None:
    """step 推进单个 stage, 不自动跑完整个 workflow."""
    executed: list[str] = []

    async def action_handler(stage: Stage) -> None:
        executed.append(stage.stage_id)

    engine.set_action_handler(action_handler)
    wf = _make_workflow(
        stages=[Stage(stage_id="s1", action="a"), Stage(stage_id="s2", action="b")],
        transitions=[Transition(from_stage="s1", to_stage="s2")],
    )
    engine.register(wf)
    # step 一次只执行 s1
    status = await engine.step("w1")
    assert status is WorkflowStatus.RUNNING  # 还没跑完
    assert "s1" in executed
    # 再 step 跑 s2
    status = await engine.step("w1")
    assert status is WorkflowStatus.SUCCEEDED


# ── resume 重启恢复 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resume_marks_interrupted_workflow_as_failed(engine: WorkflowEngine) -> None:
    """重启后 RUNNING 状态的 workflow 标为 FAILED (中断后不续跑, 与 L5 一致)."""
    wf = _make_workflow(stages=[Stage(stage_id="s1", action="a")])
    wf.status = WorkflowStatus.RUNNING  # 模拟中断时 RUNNING
    engine.register(wf)
    # 持久化 RUNNING 状态
    engine._persist(wf)  # noqa: SLF001
    status = await engine.resume("w1")
    assert status is WorkflowStatus.FAILED  # 中断后标为失败, 不续跑


@pytest.mark.asyncio
async def test_resume_unknown_returns_failed(engine: WorkflowEngine) -> None:
    status = await engine.resume("nonexistent")
    assert status is WorkflowStatus.FAILED


# ── 持久化 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_persists_workflow_to_disk(engine: WorkflowEngine) -> None:
    """start 后 workflow 状态写盘到 data/workflows/<id>.json."""
    wf = _make_workflow(stages=[Stage(stage_id="s1", action="noop")])
    engine.register(wf)
    await engine.start("w1")
    expected_path = Path(engine._base_dir) / "w1.json"  # noqa: SLF001
    assert expected_path.exists()


# ── 默认零行为变化 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_without_action_handler_succeeds_with_noop_stages(engine: WorkflowEngine) -> None:
    """无 action_handler 时 stage 视为 noop (不抛, 直接 SUCCEEDED)."""
    wf = _make_workflow(stages=[Stage(stage_id="s1", action="noop")])
    engine.register(wf)
    status = await engine.start("w1")
    assert status is WorkflowStatus.SUCCEEDED


# ── CR3-M7: 多入口 + fan-in 汇合语义 ───────────────────────────


@pytest.mark.asyncio
async def test_start_runs_all_entry_stages(engine: WorkflowEngine) -> None:
    """CR3-M7: 多个无入边的根节点必须全部启动 (此前只跑 entry_stages[0])."""
    executed: list[str] = []

    async def action_handler(stage: Stage) -> None:
        executed.append(stage.stage_id)

    engine.set_action_handler(action_handler)
    wf = _make_workflow(
        stages=[
            Stage(stage_id="root_a", action="a"),
            Stage(stage_id="root_b", action="b"),
            Stage(stage_id="child", action="c"),
        ],
        transitions=[Transition(from_stage="root_a", to_stage="child")],
    )
    engine.register(wf)
    status = await engine.start("w1")
    assert status is WorkflowStatus.SUCCEEDED
    assert set(executed) == {"root_a", "root_b", "child"}


@pytest.mark.asyncio
async def test_diamond_fan_in_waits_for_all_parents(engine: WorkflowEngine) -> None:
    """CR3-M7: 钻石 DAG (A→B, A→C, B→D, C→D) 中 D 必须等 B 和 C 都完成才执行。

    B 故意 sleep 使其晚于 C 完成; 此前 D 在首个父分支 (C) 到达时就提前运行。
    """
    finished: list[str] = []

    async def action_handler(stage: Stage) -> None:
        if stage.stage_id == "B":
            await asyncio.sleep(0.05)
        finished.append(stage.stage_id)

    engine.set_action_handler(action_handler)
    wf = _make_workflow(
        stages=[
            Stage(stage_id="A", action="a"),
            Stage(stage_id="B", action="b"),
            Stage(stage_id="C", action="c"),
            Stage(stage_id="D", action="d"),
        ],
        transitions=[
            Transition(from_stage="A", to_stage="B", kind=TransitionKind.PARALLEL),
            Transition(from_stage="A", to_stage="C", kind=TransitionKind.PARALLEL),
            Transition(from_stage="B", to_stage="D"),
            Transition(from_stage="C", to_stage="D"),
        ],
    )
    engine.register(wf)
    status = await engine.start("w1")
    assert status is WorkflowStatus.SUCCEEDED
    # D 恰好执行一次, 且在 B 与 C 都完成之后
    assert finished.count("D") == 1
    assert finished.index("D") > finished.index("B")
    assert finished.index("D") > finished.index("C")


@pytest.mark.asyncio
async def test_fan_in_with_one_skipped_branch_still_runs(engine: WorkflowEngine) -> None:
    """CR3-M7: 汇合节点的某个父分支被条件跳过时, 其余分支完成后汇合节点仍执行。"""
    executed: list[str] = []

    async def action_handler(stage: Stage) -> None:
        executed.append(stage.stage_id)

    engine.set_action_handler(action_handler)
    engine.set_condition_evaluator(lambda condition: condition == "True")
    wf = _make_workflow(
        stages=[
            Stage(stage_id="A", action="a"),
            Stage(stage_id="B", action="b"),
            Stage(stage_id="C", action="c"),
            Stage(stage_id="D", action="d"),
        ],
        transitions=[
            Transition(from_stage="A", to_stage="B", kind=TransitionKind.CONDITIONAL, condition="False"),
            Transition(from_stage="A", to_stage="C"),
            Transition(from_stage="B", to_stage="D"),
            Transition(from_stage="C", to_stage="D"),
        ],
    )
    engine.register(wf)
    status = await engine.start("w1")
    assert status is WorkflowStatus.SUCCEEDED
    assert executed.count("D") == 1
    assert "B" not in executed
    b_stage = next(s for s in engine.get("w1").stages if s.stage_id == "B")
    assert b_stage.status is StageStatus.SKIPPED


@pytest.mark.asyncio
async def test_all_parents_skipped_cascades_skip(engine: WorkflowEngine) -> None:
    """CR3-M7: 全部父分支都被条件跳过的节点级联 SKIPPED, 不执行。"""
    executed: list[str] = []

    async def action_handler(stage: Stage) -> None:
        executed.append(stage.stage_id)

    engine.set_action_handler(action_handler)
    engine.set_condition_evaluator(lambda condition: condition == "True")
    wf = _make_workflow(
        stages=[
            Stage(stage_id="A", action="a"),
            Stage(stage_id="B", action="b"),
            Stage(stage_id="C", action="c"),
        ],
        transitions=[
            Transition(from_stage="A", to_stage="B", kind=TransitionKind.CONDITIONAL, condition="False"),
            Transition(from_stage="B", to_stage="C"),
        ],
    )
    engine.register(wf)
    status = await engine.start("w1")
    assert status is WorkflowStatus.SUCCEEDED
    assert executed == ["A"]
    statuses = {s.stage_id: s.status for s in engine.get("w1").stages}
    assert statuses["B"] is StageStatus.SKIPPED
    assert statuses["C"] is StageStatus.SKIPPED


# ── CR3 复核修正: 无效边/回环边不得让 stage 静默卡死 ──────────


@pytest.mark.asyncio
async def test_dangling_source_edge_does_not_starve_target(engine: WorkflowEngine) -> None:
    """CR3 复核: from_stage 指向不存在 stage 的边被忽略, 目标 stage 正常执行。"""
    executed: list[str] = []

    async def action_handler(stage: Stage) -> None:
        executed.append(stage.stage_id)

    engine.set_action_handler(action_handler)
    wf = _make_workflow(
        stages=[Stage(stage_id="A", action="a"), Stage(stage_id="C", action="c")],
        transitions=[
            Transition(from_stage="A", to_stage="C"),
            Transition(from_stage="X_deleted", to_stage="C"),  # 悬空来源
        ],
    )
    engine.register(wf)
    status = await engine.start("w1")
    assert status is WorkflowStatus.SUCCEEDED
    assert executed == ["A", "C"]


@pytest.mark.asyncio
async def test_non_retry_self_loop_is_ignored(engine: WorkflowEngine) -> None:
    """CR3 复核: 非 RETRY 自环边不计入入度, stage 正常执行一次。"""
    executed: list[str] = []

    async def action_handler(stage: Stage) -> None:
        executed.append(stage.stage_id)

    engine.set_action_handler(action_handler)
    wf = _make_workflow(
        stages=[Stage(stage_id="A", action="a"), Stage(stage_id="B", action="b")],
        transitions=[
            Transition(from_stage="A", to_stage="B"),
            Transition(from_stage="B", to_stage="B"),  # 非 RETRY 自环
        ],
    )
    engine.register(wf)
    status = await engine.start("w1")
    assert status is WorkflowStatus.SUCCEEDED
    assert executed == ["A", "B"]


@pytest.mark.asyncio
async def test_conditional_back_edge_cycle_runs_each_stage_once(engine: WorkflowEngine) -> None:
    """CR3 复核: 下游回环边 (C→B) 不计入 B 的入度; A/B/C 各执行一次 (与旧实现一致)。"""
    executed: list[str] = []

    async def action_handler(stage: Stage) -> None:
        executed.append(stage.stage_id)

    engine.set_action_handler(action_handler)
    engine.set_condition_evaluator(lambda condition: True)
    wf = _make_workflow(
        stages=[
            Stage(stage_id="A", action="a"),
            Stage(stage_id="B", action="b"),
            Stage(stage_id="C", action="c"),
        ],
        transitions=[
            Transition(from_stage="A", to_stage="B"),
            Transition(from_stage="B", to_stage="C"),
            Transition(from_stage="C", to_stage="B", kind=TransitionKind.CONDITIONAL, condition="retry_needed"),
        ],
    )
    engine.register(wf)
    status = await engine.start("w1")
    assert status is WorkflowStatus.SUCCEEDED
    assert executed == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_unreachable_cycle_does_not_starve_reachable_join(engine: WorkflowEngine) -> None:
    """CR3 复核: 游离环 (B↔E) 中节点保持 PENDING (告警), 但不得饿死可达汇合节点 C。"""
    executed: list[str] = []

    async def action_handler(stage: Stage) -> None:
        executed.append(stage.stage_id)

    engine.set_action_handler(action_handler)
    wf = _make_workflow(
        stages=[
            Stage(stage_id="A", action="a"),
            Stage(stage_id="B", action="b"),
            Stage(stage_id="C", action="c"),
            Stage(stage_id="E", action="e"),
        ],
        transitions=[
            Transition(from_stage="A", to_stage="C"),
            Transition(from_stage="B", to_stage="C"),  # B 在游离环里, 这条边不可能被满足
            Transition(from_stage="B", to_stage="E"),
            Transition(from_stage="E", to_stage="B"),
        ],
    )
    engine.register(wf)
    status = await engine.start("w1")
    assert status is WorkflowStatus.SUCCEEDED
    assert executed == ["A", "C"]
    statuses = {s.stage_id: s.status for s in engine.get("w1").stages}
    assert statuses["B"] is StageStatus.PENDING  # 不可达, 保持 PENDING (有 warning 日志)
    assert statuses["E"] is StageStatus.PENDING
