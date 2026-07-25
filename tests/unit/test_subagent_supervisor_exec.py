"""J4 阶段 1: SubAgentSupervisor 真实执行循环测试。

覆盖:
- submit 注入 runner_factory → asyncio.create_task 后台执行 → succeeded
- runner 抛异常 → failed
- runner 超时 → timed_out
- 状态机 queued → running → succeeded/failed/timed_out
- Journal 接收 status 事件
- 终态后不再改写 (cancel 已终态幂等)
"""

from __future__ import annotations

import asyncio

import pytest

from isac.runtime.subagent.journal import SubAgentJournal
from isac.runtime.subagent.models import (
    SubAgentPolicy,
    SubAgentResult,
    SubAgentTask,
)
from isac.runtime.subagent.supervisor import SubAgentSupervisor


def _task(task_id: str = "t1", *, timeout: int = 120) -> SubAgentTask:
    return SubAgentTask(
        task_id=task_id,
        parent_agent_id="parent",
        session_id="s1",
        trace_id="tr1",
        objective="查一下天气",
        policy=SubAgentPolicy(timeout_seconds=timeout),
    )


async def _runner_success(task: SubAgentTask) -> SubAgentResult:
    """成功 runner: 返回 succeeded 结果。"""
    await asyncio.sleep(0.01)  # 模拟工作
    return SubAgentResult(
        task_id=task.task_id, status="succeeded", summary="done",
        completed_at=1,
    )


async def _runner_fail(task: SubAgentTask) -> SubAgentResult:
    """失败 runner: 抛异常。"""
    await asyncio.sleep(0.01)
    raise RuntimeError("runner failed")


async def _runner_slow(task: SubAgentTask) -> SubAgentResult:
    """超时 runner: sleep 超过 timeout。"""
    await asyncio.sleep(10)
    return SubAgentResult(task_id=task.task_id, status="succeeded", summary="never")


@pytest.mark.asyncio
async def test_submit_with_runner_succeeds() -> None:
    supervisor = SubAgentSupervisor(runner_factory=lambda t: _runner_success(t))
    run = await supervisor.submit(_task("s1"))
    assert run.status in ("queued", "running")  # submit 返回时可能还在 running
    # 等待后台 task 完成
    for _ in range(50):
        await asyncio.sleep(0.01)
        cur = await supervisor.get_status("s1")
        if cur and cur.status in ("succeeded", "failed", "timed_out"):
            break
    final = await supervisor.get_status("s1")
    assert final is not None
    assert final.status == "succeeded"
    assert final.finished_at > 0


@pytest.mark.asyncio
async def test_submit_with_runner_failing_marks_failed() -> None:
    supervisor = SubAgentSupervisor(runner_factory=lambda t: _runner_fail(t))
    await supervisor.submit(_task("f1"))
    for _ in range(50):
        await asyncio.sleep(0.01)
        cur = await supervisor.get_status("f1")
        if cur and cur.status in ("succeeded", "failed", "timed_out"):
            break
    final = await supervisor.get_status("f1")
    assert final is not None
    assert final.status == "failed"
    assert final.error_summary  # 错误摘要非空


@pytest.mark.asyncio
async def test_submit_with_runner_slow_times_out() -> None:
    # timeout=0.05s, runner sleep 10s → 必然超时
    supervisor = SubAgentSupervisor(runner_factory=lambda t: _runner_slow(t))
    await supervisor.submit(_task("to1", timeout=1))  # timeout_seconds=1 (int, 但 supervisor 内部用)
    # 注意: SubAgentPolicy.timeout_seconds 是 int, 这里用 1 秒
    # runner sleep 10s, 所以会超时; 但测试不能等 10s
    # 改用更短的 runner sleep 但仍超时:
    # 实际上 timeout_seconds=1, runner sleep 10s, asyncio.wait_for 会在 1s 后 cancel
    # 测试等待 2s 让超时生效
    for _ in range(250):  # 250 * 0.01 = 2.5s
        await asyncio.sleep(0.01)
        cur = await supervisor.get_status("to1")
        if cur and cur.status in ("succeeded", "failed", "timed_out"):
            break
    final = await supervisor.get_status("to1")
    assert final is not None
    assert final.status == "timed_out"


@pytest.mark.asyncio
async def test_submit_status_transitions_queued_to_running(tmp_path) -> None:
    """submit 后立即状态应为 queued 或 running; 后台 task 启动后变 running。"""
    started = asyncio.Event()

    async def _runner(task: SubAgentTask) -> SubAgentResult:
        started.set()
        await asyncio.sleep(0.05)
        return SubAgentResult(task_id=task.task_id, status="succeeded", summary="ok", completed_at=1)

    supervisor = SubAgentSupervisor(runner_factory=_runner)
    run = await supervisor.submit(_task("tr1"))
    assert run.status in ("queued", "running")
    # 等 runner 启动
    await asyncio.wait_for(started.wait(), timeout=1.0)
    cur = await supervisor.get_status("tr1")
    assert cur is not None
    assert cur.status == "running"
    # 等完成
    for _ in range(100):
        await asyncio.sleep(0.01)
        cur = await supervisor.get_status("tr1")
        if cur and cur.status in ("succeeded", "failed", "timed_out"):
            break
    final = await supervisor.get_status("tr1")
    assert final is not None
    assert final.status == "succeeded"


@pytest.mark.asyncio
async def test_journal_receives_status_events(tmp_path) -> None:
    """后台执行过程中 Journal 应收到 status 事件 (running/succeeded)。"""
    journal = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal.start()
    try:
        supervisor = SubAgentSupervisor(
            journal=journal, runner_factory=lambda t: _runner_success(t)
        )
        await supervisor.submit(_task("j1"))
        # 等后台 task 完成 (bg_task done 表示 _run_task 已写完所有 journal event)
        bg_task = supervisor._tasks.get("j1")
        if bg_task is not None:
            try:
                await asyncio.wait_for(bg_task, timeout=2.0)
            except (asyncio.CancelledError, TimeoutError):
                pass
        events = await supervisor.fetch_log("j1", 0, 100)
        # 至少有 running + succeeded 两个事件
        event_types = [e.event_type for e in events]
        assert "status" in event_types
        summaries = [e.summary for e in events]
        assert any("running" in s for s in summaries)
        assert any("succeeded" in s for s in summaries)
    finally:
        await journal.stop()


@pytest.mark.asyncio
async def test_cancel_running_task_marks_cancelled() -> None:
    """cancel 一个正在 running 的 task → 状态置 cancelled, 后台 task 取消。"""
    started = asyncio.Event()

    async def _runner(task: SubAgentTask) -> SubAgentResult:
        started.set()
        await asyncio.sleep(5)
        return SubAgentResult(task_id=task.task_id, status="succeeded", summary="never")

    supervisor = SubAgentSupervisor(runner_factory=_runner)
    await supervisor.submit(_task("c1"))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    # cancel
    cancelled = await supervisor.cancel("c1")
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    # 后台 task 应被取消 (不再 running)
    await asyncio.sleep(0.05)
    final = await supervisor.get_status("c1")
    assert final is not None
    assert final.status == "cancelled"


@pytest.mark.asyncio
async def test_submit_without_runner_keeps_skeleton_behavior() -> None:
    """未注入 runner_factory 时保持骨架行为: 返回 queued 不启动后台 task。"""
    supervisor = SubAgentSupervisor()  # 无 runner_factory
    run = await supervisor.submit(_task("no-runner"))
    assert run.status == "queued"
    # 等一段时间, 状态不变
    await asyncio.sleep(0.05)
    cur = await supervisor.get_status("no-runner")
    assert cur is not None
    assert cur.status == "queued"
