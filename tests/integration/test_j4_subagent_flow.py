"""J4 阶段 5: SubAgent Runtime 端到端集成测试。

全链路: delegate_task 工具 → SubAgentSupervisor.submit → asyncio.create_task
→ runner (Fake) → SubAgentJournal 写事件 → 工具 poll get_status 终态 → 返回结果。

覆盖:
- 完整 delegate_task → supervisor → journal 链路
- 派生任务失败 → 工具返回 error
- 派生任务取消 (cancel) → 工具返回 cancelled
- Journal 持久化事件可经 fetch_log 读回
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from isac.agent.tools.base import ToolContext
from isac.agent.tools.subagent import DelegateTaskTool
from isac.core.types import AgentContext
from isac.gateway.models import Session
from isac.runtime.subagent.journal import SubAgentJournal
from isac.runtime.subagent.models import SubAgentResult, SubAgentTask
from isac.runtime.subagent.supervisor import SubAgentSupervisor


async def _runner_success(task: SubAgentTask) -> SubAgentResult:
    await asyncio.sleep(0.01)
    return SubAgentResult(
        task_id=task.task_id, status="succeeded", summary="天气: 晴, 25°C",
        completed_at=1,
    )


async def _runner_fail(task: SubAgentTask) -> SubAgentResult:
    await asyncio.sleep(0.01)
    raise RuntimeError("子任务执行失败: 网络不可用")


async def _runner_slow(task: SubAgentTask) -> SubAgentResult:
    await asyncio.sleep(5)
    return SubAgentResult(task_id=task.task_id, status="succeeded", summary="never")


def _make_ctx(services: dict[str, Any], args: dict[str, Any]) -> ToolContext:
    session = Session(session_id="s1", user_id="u1", platform="test")
    return ToolContext(
        args=args,
        agent_context=AgentContext(
            session=session, user_profile=None, current_message=None, services={},
        ),
        services=services,
    )


def _make_services(
    supervisor: SubAgentSupervisor, *, task_depth: int = 0
) -> dict[str, Any]:
    return {"subagent_supervisor": supervisor, "task_depth": task_depth, "task_max_depth": 3}


@pytest.mark.asyncio
async def test_delegate_to_supervisor_full_chain(tmp_path: Path) -> None:
    """E2E: delegate_task → supervisor.submit → runner → journal → 终态 + 事件可读。"""
    journal = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal.start()
    try:
        supervisor = SubAgentSupervisor(
            journal=journal, runner_factory=_runner_success
        )
        services = _make_services(supervisor)
        tool = DelegateTaskTool()
        ctx = _make_ctx(services, {"objective": "查天气", "summary": "用户问"})
        result = await tool.execute(ctx)
        assert not result.is_error
        assert "天气" in result.content
        # journal 应有 running + succeeded 事件
        runs = await supervisor.list_runs()
        assert len(runs) >= 1
        task_id = runs[0].task_id
        events = await supervisor.fetch_log(task_id, 0, 100)
        summaries = [e.summary for e in events]
        assert any("running" in s for s in summaries)
        assert any("succeeded" in s for s in summaries)
    finally:
        await journal.stop()


@pytest.mark.asyncio
async def test_delegate_failing_returns_error_to_llm(tmp_path: Path) -> None:
    """E2E: runner 抛异常 → 工具返回 is_error=True + 错误摘要给 LLM。"""
    journal = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal.start()
    try:
        supervisor = SubAgentSupervisor(
            journal=journal, runner_factory=_runner_fail
        )
        services = _make_services(supervisor)
        tool = DelegateTaskTool()
        ctx = _make_ctx(services, {"objective": "查天气"})
        result = await tool.execute(ctx)
        assert result.is_error
        assert "失败" in result.content or "网络不可用" in result.content
    finally:
        await journal.stop()


@pytest.mark.asyncio
async def test_delegate_cancel_via_supervisor(tmp_path: Path) -> None:
    """E2E: supervisor.cancel → runner 收到 CancelledError → 状态 cancelled。"""
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

    journal = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal.start()
    try:
        supervisor = SubAgentSupervisor(journal=journal, runner_factory=_runner)
        # 派生一个任务
        task = SubAgentTask(
            task_id="e2e-cancel", parent_agent_id="a1", session_id="s1",
            trace_id="tr1", objective="x",
        )
        await supervisor.submit(task)
        await asyncio.wait_for(started.wait(), timeout=1.0)
        # cancel
        cancelled = await supervisor.cancel("e2e-cancel")
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        await asyncio.wait_for(cancelled_event.wait(), timeout=1.0)
        assert cancelled_event.is_set()
    finally:
        await journal.stop()


@pytest.mark.asyncio
async def test_delegate_timeout_returns_current_status(tmp_path: Path) -> None:
    """E2E: runner 慢, 工具等待超时 → 返回 running 状态 (不取消, 后台继续)。"""
    journal = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal.start()
    try:
        supervisor = SubAgentSupervisor(journal=journal, runner_factory=_runner_slow)
        services = _make_services(supervisor)
        tool = DelegateTaskTool()
        ctx = _make_ctx(services, {"objective": "x", "_wait_timeout": 0.1})
        result = await tool.execute(ctx)
        # 超时不应该是 is_error, 而是提示仍在执行
        assert not result.is_error
        assert "执行" in result.content or "running" in result.content.lower()
        # cancel 清理后台 task
        runs = await supervisor.list_runs()
        if runs:
            await supervisor.cancel(runs[0].task_id)
    finally:
        await journal.stop()


@pytest.mark.asyncio
async def test_control_api_routes_subagent_full_chain(tmp_path: Path) -> None:
    """E2E: Control API routes_subagent 派生 + 查询 + 取消全链路。

    注意: TestClient 用独立 event loop, supervisor 后台 task 无法与测试共享。
    所以先在测试 event loop 里 submit + 等完成, 再调 API 查询已终态的 run。
    """
    from fastapi.testclient import TestClient

    from isac.control.api.server import create_control_app
    from isac.observability import get_default_metrics

    journal = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal.start()
    try:
        supervisor = SubAgentSupervisor(journal=journal, runner_factory=_runner_success)
        # 在测试 event loop 里 submit + 等完成
        task = SubAgentTask(
            task_id="api-e2e", parent_agent_id="a1", session_id="s1",
            trace_id="tr1", objective="查天气",
        )
        await supervisor.submit(task)
        bg_task = supervisor._tasks.get("api-e2e")
        for _ in range(50):
            await asyncio.sleep(0.01)
            run = await supervisor.get_status("api-e2e")
            if run and run.status in ("succeeded", "failed", "timed_out", "cancelled"):
                break
        assert run is not None
        assert run.status == "succeeded"
        # 等 bg_task 完全完成 (确保 _transition 的 journal.append 已写完, 避免
        # finally journal.stop() 后 bg_task 还在写导致 "closed database" 错误)
        if bg_task is not None:
            try:
                await asyncio.wait_for(bg_task, timeout=2.0)
            except (asyncio.CancelledError, TimeoutError):
                pass

        class _StubAM:
            async def list(self): return []
            async def get(self, _): return None

        app = create_control_app(
            _StubAM(), object(), object(), object(),
            {"api_token": "t"}, metrics=get_default_metrics(),
            subagent_supervisor=supervisor,
        )
        client = TestClient(app)
        # 查询已终态的 run
        resp = client.get(
            "/api/v1/subagent-runs/api-e2e",
            headers={"Authorization": "Bearer t"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "succeeded"
        # 读事件
        resp = client.get(
            "/api/v1/subagent-runs/api-e2e/events?after_seq=0&limit=50",
            headers={"Authorization": "Bearer t"},
        )
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) >= 2  # running + succeeded
    finally:
        await journal.stop()
