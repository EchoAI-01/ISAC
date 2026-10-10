"""J4 SubAgent Runtime 框架骨架测试。

覆盖权限交集、submit 返回 queued、状态查询、幂等取消、Journal (task_id,seq) 追加与分页,
以及工具在无 Supervisor 时的友好错误。真实子 Agent 执行循环属实现节点范畴, 不在此覆盖。
"""

from __future__ import annotations

import asyncio

from isac.agent.tools.base import ToolContext, ToolPermission
from isac.agent.tools.subagent import CancelSubagentTool, DelegateTaskTool, SubagentStatusTool
from isac.core.types import AgentContext
from isac.runtime.subagent.journal import SubAgentJournal
from isac.runtime.subagent.models import SubAgentEvent, SubAgentPolicy, SubAgentTask
from isac.runtime.subagent.supervisor import SubAgentSupervisor


def _requester(agent_id: str) -> AgentContext:
    return AgentContext(session=object(), user_profile=None, current_message=object(), services={"agent_id": agent_id})


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


def test_policy_intersect_explicit_empty_allowlist_denies_all() -> None:
    """Fix-5: 显式空 allowlist 必须是"拒绝全部"而不是"该层不约束"; 之前的 fail-open
    实现会让任一侧空列表就继承另一方, 与 DEVELOPMENT_PLAN.md 承诺的"空集拒绝
    全部"相反, 且 allowed_tools 算出来的交集从未在任何地方真正被执行, 一旦有
    调用方显式传空列表表示收紧权限, fail-open 会悄悄放行本该被拒绝的工具。"""
    parent = SubAgentPolicy(allowed_tools=["read_file"])
    task = SubAgentPolicy(allowed_tools=[])
    assert parent.intersect(task).allowed_tools == []


def test_policy_default_allowed_tools_is_a_safe_nonempty_baseline() -> None:
    """严格交集修复后, 如果 SubAgentPolicy() 裸默认值仍是空列表, 两个都用默认值
    的策略求交集会恒为空集, delegate_task 功能等于报废。默认值必须是一个明确
    写出来的安全只读工具子集, 不含 bash/write_file/send_* 等高风险工具。"""
    policy = SubAgentPolicy()
    assert policy.allowed_tools  # 非空
    assert "bash" not in policy.allowed_tools
    assert "write_file" not in policy.allowed_tools
    assert not any(name.startswith("send_") for name in policy.allowed_tools)


def test_policy_intersect_of_two_defaults_is_still_the_safe_baseline() -> None:
    """两侧都不显式配置策略 (纯默认值) 时, 严格交集不能因为"看起来都是默认值"
    就退化成空集——默认值本身就该是交集后仍然有效的安全基线。"""
    effective = SubAgentPolicy().intersect(SubAgentPolicy())
    assert effective.allowed_tools == sorted(SubAgentPolicy().allowed_tools)


async def test_submit_returns_queued_run() -> None:
    supervisor = SubAgentSupervisor()
    run = await supervisor.submit(_task())
    assert run.status == "queued"
    assert run.task_id == "t1"
    assert (await supervisor.get_status("t1")) is run


async def test_run_records_parent_agent_id() -> None:
    """Fix-10: SubAgentRun 必须记住创建它的 Agent, 否则无法做跨 Agent 鉴权,
    也无法按 agent_id 过滤 Control API 的 list_subagent_runs。"""
    supervisor = SubAgentSupervisor()
    task = SubAgentTask(
        task_id="owned-by-a", parent_agent_id="agent-a", session_id="s1", trace_id="tr1", objective="x",
    )
    run = await supervisor.submit(task)
    assert run.parent_agent_id == "agent-a"


async def test_other_agent_cannot_query_status_of_task_it_does_not_own() -> None:
    supervisor = SubAgentSupervisor()
    task = SubAgentTask(
        task_id="owned-by-a", parent_agent_id="agent-a", session_id="s1", trace_id="tr1", objective="x",
    )
    await supervisor.submit(task)
    try:
        await supervisor.get_status("owned-by-a", _requester("agent-b"))
    except PermissionError:
        pass
    else:
        raise AssertionError("Agent B 查询 Agent A 的子任务必须被拒绝")


async def test_owning_agent_can_query_its_own_task_status() -> None:
    supervisor = SubAgentSupervisor()
    task = SubAgentTask(
        task_id="owned-by-a", parent_agent_id="agent-a", session_id="s1", trace_id="tr1", objective="x",
    )
    await supervisor.submit(task)
    run = await supervisor.get_status("owned-by-a", _requester("agent-a"))
    assert run is not None


async def test_admin_caller_without_requester_can_query_any_task() -> None:
    """requester=None (控制面/管理员调用, 不代表某个具体 Agent) 必须放行, 不受
    跨 Agent 归属限制。"""
    supervisor = SubAgentSupervisor()
    task = SubAgentTask(
        task_id="owned-by-a", parent_agent_id="agent-a", session_id="s1", trace_id="tr1", objective="x",
    )
    await supervisor.submit(task)
    run = await supervisor.get_status("owned-by-a", None)
    assert run is not None


async def test_other_agent_cannot_cancel_task_it_does_not_own() -> None:
    supervisor = SubAgentSupervisor()
    task = SubAgentTask(
        task_id="owned-by-a", parent_agent_id="agent-a", session_id="s1", trace_id="tr1", objective="x",
    )
    await supervisor.submit(task)
    try:
        await supervisor.cancel("owned-by-a", _requester("agent-b"))
    except PermissionError:
        pass
    else:
        raise AssertionError("Agent B 取消 Agent A 的子任务必须被拒绝")


async def test_list_runs_filters_by_parent_agent_id() -> None:
    supervisor = SubAgentSupervisor()
    await supervisor.submit(SubAgentTask(
        task_id="a1", parent_agent_id="agent-a", session_id="s1", trace_id="tr1", objective="x",
    ))
    await supervisor.submit(SubAgentTask(
        task_id="b1", parent_agent_id="agent-b", session_id="s1", trace_id="tr1", objective="x",
    ))
    runs = await supervisor.list_runs(filters={"parent_agent_id": "agent-a"})
    assert {r.task_id for r in runs} == {"a1"}


async def test_submit_rejects_task_beyond_policy_max_depth() -> None:
    supervisor = SubAgentSupervisor(parent_policy=SubAgentPolicy(max_depth=1))
    task = _task("too-deep", SubAgentPolicy(max_depth=3))
    task.context["task_depth"] = 2

    try:
        await supervisor.submit(task)
    except ValueError as exc:
        assert "递归深度" in str(exc)
    else:
        raise AssertionError("超过 max_depth 的任务必须被 Supervisor 拒绝")


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


async def test_journal_truncates_summary_to_max_log_bytes(tmp_path) -> None:
    """Fix-9: summary 之前完全不受 max_log_bytes 约束, 超长/异常内容可以无限
    占用日志存储; 落库前必须按 (调用方传入的, 或默认策略值) 上限截断。"""
    journal = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal.start()
    try:
        long_summary = "A" * 1000
        await journal.append(
            SubAgentEvent(task_id="t1", seq=1, event_type="status", timestamp=1, summary=long_summary),
            max_log_bytes=100,
        )
        events = await journal.fetch_after("t1", 0, 10)
        assert len(events[0].summary.encode("utf-8")) <= 100
    finally:
        await journal.stop()


async def test_journal_default_max_log_bytes_when_not_specified(tmp_path) -> None:
    """未显式传 max_log_bytes 时应用 SubAgentPolicy 的默认上限, 而不是完全不限制。"""
    journal = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal.start()
    try:
        short_summary = "正常长度的摘要"
        await journal.append(
            SubAgentEvent(task_id="t1", seq=1, event_type="status", timestamp=1, summary=short_summary)
        )
        events = await journal.fetch_after("t1", 0, 10)
        # 默认上限远大于这条短摘要, 不应被误截断
        assert events[0].summary == short_summary
    finally:
        await journal.stop()


async def test_supervisor_persists_events_truncated_by_task_effective_policy(tmp_path) -> None:
    """端到端: Supervisor 内部产生的状态事件也要按该任务的生效策略截断, 不能只在
    journal 单测层面截断而 Supervisor 从不传这个参数。"""
    journal = SubAgentJournal(str(tmp_path / "journal.db"))
    await journal.start()
    try:
        supervisor = SubAgentSupervisor(journal=journal)
        long_objective = "x" * 2000

        async def _runner(task: SubAgentTask):
            from isac.runtime.subagent.models import SubAgentResult

            return SubAgentResult(task_id=task.task_id, status="succeeded", summary=long_objective)

        supervisor.set_runner_factory(_runner)
        task = _task("t-trunc", SubAgentPolicy(max_log_bytes=50))
        await supervisor.submit(task)
        for _ in range(50):
            run = await supervisor.get_status("t-trunc")
            if run is not None and run.status == "succeeded":
                break
            await asyncio.sleep(0.01)
        events = await journal.fetch_after("t-trunc", 0, 10)
        succeeded_events = [e for e in events if "succeeded" in e.summary]
        assert succeeded_events
        assert len(succeeded_events[0].summary.encode("utf-8")) <= 50
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


async def test_m10_list_runs_enforces_requester_isolation() -> None:
    """M10: requester 带 Agent 身份时 list_runs 强制只返回其自己创建的子任务。

    此前任何 Agent 都能 enumerate 出**所有** Agent 的 task_id+status
    (status/log/cancel 均有 _authorize 边界, 唯独 list 没有)。控制面
    (requester=None) 不受身份过滤影响。
    """
    supervisor = SubAgentSupervisor()
    await supervisor.submit(SubAgentTask(
        task_id="a1", parent_agent_id="agent-a", session_id="s1", trace_id="tr1", objective="x",
    ))
    await supervisor.submit(SubAgentTask(
        task_id="b1", parent_agent_id="agent-b", session_id="s1", trace_id="tr1", objective="x",
    ))
    # agent-a 只能看到自己的子任务, 看不到 agent-b 的
    runs_a = await supervisor.list_runs(requester=_requester("agent-a"))
    assert {r.task_id for r in runs_a} == {"a1"}
    # 控制面 (requester=None) 仍能看到全部
    runs_all = await supervisor.list_runs()
    assert {r.task_id for r in runs_all} == {"a1", "b1"}
