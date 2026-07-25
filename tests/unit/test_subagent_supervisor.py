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
