"""J4 阶段 3: 取消传播 + 重启恢复测试。

覆盖:
- cancel 一个 running task → asyncio.Task.cancel() 传播到 runner
- runner 收到 CancelledError → 状态置 cancelled (不是 failed/timed_out)
- restore_interrupted(): 重启时把 running/queued 标记为 cancelled (中断后不恢复旧进度)
- Journal 持久化: 重启后 fetch_log 仍能读到历史事件
"""

from __future__ import annotations

import asyncio

import pytest

from isac.runtime.subagent.journal import SubAgentJournal
from isac.runtime.subagent.models import (
    SubAgentEvent,
    SubAgentPolicy,
    SubAgentResult,
    SubAgentRun,
    SubAgentTask,
)
from isac.runtime.subagent.supervisor import SubAgentSupervisor


def _task(task_id: str = "t1") -> SubAgentTask:
    return SubAgentTask(
        task_id=task_id,
        parent_agent_id="parent",
        session_id="s1",
        trace_id="tr1",
        objective="查天气",
        policy=SubAgentPolicy(timeout_seconds=120),
    )


@pytest.mark.asyncio
async def test_cancel_propagates_to_running_runner() -> None:
    """cancel running task → runner 收到 CancelledError → 状态 cancelled (不是 failed)。"""
    started = asyncio.Event()
    cancelled_event = asyncio.Event()

    async def _runner(task: SubAgentTask) -> SubAgentResult:
        started.set()
        try:
            await asyncio.sleep(5)
            return SubAgentResult(task_id=task.task_id, status="succeeded", summary="never")
        except asyncio.CancelledError:
            cancelled_event.set()
            raise

    supervisor = SubAgentSupervisor(runner_factory=_runner)
    await supervisor.submit(_task("c1"))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    # 取消
    cancelled = await supervisor.cancel("c1")
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    # runner 应收到 CancelledError
    await asyncio.wait_for(cancelled_event.wait(), timeout=1.0)
    assert cancelled_event.is_set()
    # 最终状态
    final = await supervisor.get_status("c1")
    assert final is not None
    assert final.status == "cancelled"


@pytest.mark.asyncio
async def test_restore_interrupted_marks_running_as_cancelled(tmp_path) -> None:
    """重启恢复: 把 running/queued 状态的 task 标记为 cancelled (中断后不恢复旧进度)。"""
    journal = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal.start()
    try:
        # 模拟第一次运行: 写入 running 状态的 run
        supervisor1 = SubAgentSupervisor(journal=journal)
        # 手动写入一个 running 状态的 run (不启动 runner)
        run = SubAgentRun(task_id="r1", status="running", started_at=100, updated_at=100)
        supervisor1._runs["r1"] = run
        await journal.upsert_run(run)
        # 再写入一个 queued 状态
        run2 = SubAgentRun(task_id="r2", status="queued", started_at=100, updated_at=100)
        supervisor1._runs["r2"] = run2
        await journal.upsert_run(run2)
    finally:
        await journal.stop()

    # 模拟重启: 新 supervisor + restore_interrupted
    journal2 = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal2.start()
    try:
        supervisor2 = SubAgentSupervisor(journal=journal2)
        await supervisor2.restore_interrupted()
        # r1 和 r2 应都被标记为 cancelled
        r1 = await supervisor2.get_status("r1")
        assert r1 is not None
        assert r1.status == "cancelled"
        assert r1.finished_at > 0
        r2 = await supervisor2.get_status("r2")
        assert r2 is not None
        assert r2.status == "cancelled"
    finally:
        await journal2.stop()


@pytest.mark.asyncio
async def test_restore_interrupted_keeps_terminal_statuses(tmp_path) -> None:
    """重启恢复: 已终态 (succeeded/failed/cancelled/timed_out) 的 run 不被改写。"""
    journal = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal.start()
    try:
        # 写入各种终态 run
        for tid, status in [("s1", "succeeded"), ("f1", "failed"), ("c1", "cancelled"), ("to1", "timed_out")]:
            run = SubAgentRun(task_id=tid, status=status, started_at=100, updated_at=100, finished_at=200)
            await journal.upsert_run(run)
    finally:
        await journal.stop()

    journal2 = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal2.start()
    try:
        supervisor = SubAgentSupervisor(journal=journal2)
        await supervisor.restore_interrupted()
        # 终态不变
        for tid, expected in [("s1", "succeeded"), ("f1", "failed"), ("c1", "cancelled"), ("to1", "timed_out")]:
            run = await supervisor.get_status(tid)
            assert run is not None
            assert run.status == expected
    finally:
        await journal2.stop()


@pytest.mark.asyncio
async def test_restore_interrupted_no_journal_is_noop() -> None:
    """无 journal 时 restore_interrupted 不报错 (no-op)。"""
    supervisor = SubAgentSupervisor()  # 无 journal
    await supervisor.restore_interrupted()  # 不应抛异常


@pytest.mark.asyncio
async def test_journal_persists_events_across_restart(tmp_path) -> None:
    """Journal 持久化: 重启后 fetch_log 仍能读到历史事件。"""
    journal = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal.start()
    try:
        await journal.append(SubAgentEvent(task_id="p1", seq=0, event_type="status", timestamp=1, summary="running"))
        await journal.append(SubAgentEvent(task_id="p1", seq=0, event_type="status", timestamp=2, summary="succeeded"))
    finally:
        await journal.stop()

    journal2 = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal2.start()
    try:
        events = await journal2.fetch_after("p1", 0, 100)
        assert len(events) == 2
        assert events[0].summary == "running"
        assert events[1].summary == "succeeded"
        # seq 应自动分配为 1, 2
        assert events[0].seq == 1
        assert events[1].seq == 2
    finally:
        await journal2.stop()
