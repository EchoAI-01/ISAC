"""J4 SubAgent Runtime 框架骨架测试。

覆盖权限交集、submit 返回 queued、状态查询、幂等取消、Journal (task_id,seq) 追加与分页,
以及工具在无 Supervisor 时的友好错误。真实子 Agent 执行循环属实现节点范畴, 不在此覆盖。
"""

from __future__ import annotations

from isac.agent.tools.base import ToolContext, ToolPermission
from isac.agent.tools.subagent import CancelSubagentTool, DelegateTaskTool, SubagentStatusTool
from isac.runtime.subagent.journal import SubAgentJournal
from isac.runtime.subagent.models import SubAgentEvent, SubAgentPolicy, SubAgentTask
from isac.runtime.subagent.supervisor import SubAgentSupervisor


def _task(task_id: str = "t1", policy: SubAgentPolicy | None = None) -> SubAgentTask:
    return SubAgentTask(
        task_id=task_id,
        parent_agent_id="parent",
        session_id="s1",
        trace_id="tr1",
        objective="查一下天气",
        policy=policy or SubAgentPolicy(),
    )


def test_policy_intersect_takes_stricter() -> None:
    parent = SubAgentPolicy(max_tokens=8000, allowed_tools=["bash", "read_file"], allow_channel_send=True)
    task = SubAgentPolicy(max_tokens=2000, allowed_tools=["read_file"], allow_channel_send=False)
    effective = parent.intersect(task)
    assert effective.max_tokens == 2000
    assert effective.allowed_tools == ["read_file"]
    assert effective.allow_channel_send is False


def test_policy_intersect_empty_allowlist_inherits() -> None:
    parent = SubAgentPolicy(allowed_tools=["read_file"])
    task = SubAgentPolicy(allowed_tools=[])
    # 任务侧空表示该层不额外约束 → 继承父允许
    assert parent.intersect(task).allowed_tools == ["read_file"]


async def test_submit_returns_queued_run() -> None:
    supervisor = SubAgentSupervisor()
    run = await supervisor.submit(_task())
    assert run.status == "queued"
    assert run.task_id == "t1"
    assert (await supervisor.get_status("t1")) is run


async def test_cancel_is_idempotent() -> None:
    supervisor = SubAgentSupervisor()
    await supervisor.submit(_task("t2"))
    first = await supervisor.cancel("t2")
    assert first is not None
    assert first.status == "cancelled"
    # 再次取消不报错, 状态不变
    second = await supervisor.cancel("t2")
    assert second is not None
    assert second.status == "cancelled"


async def test_cancel_unknown_returns_none() -> None:
    supervisor = SubAgentSupervisor()
    assert await supervisor.cancel("missing") is None


async def test_list_runs_status_filter() -> None:
    supervisor = SubAgentSupervisor()
    await supervisor.submit(_task("a"))
    await supervisor.submit(_task("b"))
    await supervisor.cancel("b")
    cancelled = await supervisor.list_runs(filters={"status": "cancelled"})
    assert {r.task_id for r in cancelled} == {"b"}


async def test_journal_append_and_paginate(tmp_path) -> None:
    journal = SubAgentJournal(str(tmp_path / "subagent" / "journal.db"))
    await journal.start()
    try:
        for seq in range(1, 4):
            await journal.append(
                SubAgentEvent(task_id="t1", seq=seq, event_type="status", timestamp=seq, summary=f"step {seq}")
            )
        page = await journal.fetch_after("t1", after_seq=1, limit=10)
        assert [e.seq for e in page] == [2, 3]
    finally:
        await journal.stop()


async def test_journal_sanitizes_sensitive_metadata(tmp_path) -> None:
    journal = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal.start()
    try:
        await journal.append(
            SubAgentEvent(
                task_id="t1",
                seq=1,
                event_type="tool",
                timestamp=1,
                summary="调用工具",
                metadata={"api_key": "sk-x", "safe": "ok"},
            )
        )
        events = await journal.fetch_after("t1", 0, 10)
        assert events[0].metadata == {"safe": "ok"}
    finally:
        await journal.stop()


async def test_supervisor_fetch_log_delegates_to_journal(tmp_path) -> None:
    journal = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal.start()
    try:
        supervisor = SubAgentSupervisor(journal=journal)
        await supervisor.submit(_task("t1"))
        await journal.append(SubAgentEvent(task_id="t1", seq=1, event_type="status", timestamp=1, summary="hi"))
        events = await supervisor.fetch_log("t1", 0, 10)
        assert len(events) == 1
        assert events[0].summary == "hi"
    finally:
        await journal.stop()


async def test_delegate_tool_without_supervisor_errors() -> None:
    tool = DelegateTaskTool()
    ctx = ToolContext(args={"objective": "x"}, agent_context=object(), services={})  # type: ignore[arg-type]
    result = await tool.execute(ctx)
    assert result.is_error is True


async def test_status_and_cancel_tools_delegate_to_supervisor() -> None:
    supervisor = SubAgentSupervisor()
    await supervisor.submit(_task("t9"))
    services = {"subagent_supervisor": supervisor}

    status_tool = SubagentStatusTool()
    status_ctx = ToolContext(args={"task_id": "t9"}, agent_context=object(), services=services)  # type: ignore[arg-type]
    status_result = await status_tool.execute(status_ctx)
    assert "queued" in status_result.content

    cancel_tool = CancelSubagentTool()
    cancel_ctx = ToolContext(args={"task_id": "t9"}, agent_context=object(), services=services)  # type: ignore[arg-type]
    cancel_result = await cancel_tool.execute(cancel_ctx)
    assert "cancelled" in cancel_result.content


def test_subagent_tool_default_policy() -> None:
    permission = ToolPermission()
    # J4-2: delegate_task 从 deny 改 restricted (需显式授权, 但不再是默认禁用)
    assert permission.check("delegate_task") == "restricted"
    assert permission.check("subagent_status") == "restricted"
