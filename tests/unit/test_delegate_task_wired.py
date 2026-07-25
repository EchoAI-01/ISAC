"""J4 阶段 2: delegate_task 工具接线 + H3 TaskRunner 迁移测试。

覆盖:
- DelegateTaskTool 真实链路: 调 supervisor.submit → 等终态 → 返回结果摘要
- DelegateTaskTool 无 supervisor → 友好错误
- DelegateTaskTool 等待超时 → 返回当前状态
- TaskTool 迁移: task 工具委托 supervisor.submit (保留 task_depth 递归深度限制)
- TaskTool 深度上限 → 拒绝继续委派
- DEFAULT_POLICY delegate_task 从 deny 改 restricted
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from isac.agent.tools.base import ToolContext, ToolPermission
from isac.agent.tools.subagent import DelegateTaskTool
from isac.agent.tools.utility.task import TaskTool
from isac.core.types import AgentContext
from isac.gateway.models import Session
from isac.runtime.subagent.models import SubAgentResult, SubAgentTask
from isac.runtime.subagent.supervisor import SubAgentSupervisor


async def _runner_success(task: SubAgentTask) -> SubAgentResult:
    await asyncio.sleep(0.01)
    return SubAgentResult(
        task_id=task.task_id, status="succeeded", summary="子任务结果: 天气晴朗",
        completed_at=1,
    )


async def _runner_fail(task: SubAgentTask) -> SubAgentResult:
    await asyncio.sleep(0.01)
    raise RuntimeError("子任务执行失败")


def _make_ctx(services: dict[str, Any], args: dict[str, Any]) -> ToolContext:
    session = Session(session_id="s1", user_id="u1", platform="test")
    return ToolContext(
        args=args,
        agent_context=AgentContext(
            session=session, user_profile=None, current_message=None, services={},
        ),
        services=services,
    )


def _make_supervisor_services(runner_factory=None) -> dict[str, Any]:
    return {"subagent_supervisor": SubAgentSupervisor(runner_factory=runner_factory)}


@pytest.mark.asyncio
async def test_delegate_task_succeeds_returns_summary() -> None:
    services = _make_supervisor_services(_runner_success)
    tool = DelegateTaskTool()
    ctx = _make_ctx(services, {"objective": "查天气", "summary": "用户问天气"})
    result = await tool.execute(ctx)
    assert not result.is_error
    assert "天气晴朗" in result.content


@pytest.mark.asyncio
async def test_delegate_task_failing_returns_error() -> None:
    services = _make_supervisor_services(_runner_fail)
    tool = DelegateTaskTool()
    ctx = _make_ctx(services, {"objective": "查天气"})
    result = await tool.execute(ctx)
    assert result.is_error
    assert "failed" in result.content.lower() or "失败" in result.content


@pytest.mark.asyncio
async def test_delegate_task_without_supervisor_returns_error() -> None:
    tool = DelegateTaskTool()
    ctx = _make_ctx({}, {"objective": "查天气"})
    result = await tool.execute(ctx)
    assert result.is_error
    assert "未配置" in result.content or "SubAgent" in result.content


@pytest.mark.asyncio
async def test_delegate_task_missing_objective_returns_error() -> None:
    services = _make_supervisor_services(_runner_success)
    tool = DelegateTaskTool()
    ctx = _make_ctx(services, {})  # 无 objective
    result = await tool.execute(ctx)
    assert result.is_error


@pytest.mark.asyncio
async def test_delegate_task_timeout_returns_current_status() -> None:
    """runner 慢但工具等待超时 → 返回 running 状态。"""
    async def _slow_runner(task: SubAgentTask) -> SubAgentResult:
        await asyncio.sleep(5)
        return SubAgentResult(task_id=task.task_id, status="succeeded", summary="never")

    services = _make_supervisor_services(_slow_runner)
    tool = DelegateTaskTool()
    # 工具内部等待超时设为 0.1s (通过 args 传入)
    ctx = _make_ctx(services, {"objective": "查天气", "_wait_timeout": 0.1})
    result = await tool.execute(ctx)
    # 超时不应是 is_error, 而是返回当前状态 (running 或 queued)
    # 但工具应给出明确提示
    assert "超时" in result.content or "running" in result.content.lower() or "queued" in result.content.lower()


@pytest.mark.asyncio
async def test_task_tool_delegates_to_supervisor() -> None:
    """H3 迁移: task 工具内部委托 supervisor.submit, 不再走 task_runner。"""
    services = _make_supervisor_services(_runner_success)
    tool = TaskTool()
    ctx = _make_ctx(services, {"task": "查天气", "budget_tokens": 2000})
    result = await tool.execute(ctx)
    assert not result.is_error
    assert "天气晴朗" in result.content


@pytest.mark.asyncio
async def test_task_tool_depth_limit_rejects() -> None:
    """递归深度上限 (默认 3): task_depth >= max_depth 时拒绝继续委派。"""
    services = _make_supervisor_services(_runner_success)
    services["task_depth"] = 3  # 已达上限
    services["task_max_depth"] = 3
    tool = TaskTool()
    ctx = _make_ctx(services, {"task": "查天气"})
    result = await tool.execute(ctx)
    assert result.is_error
    assert "递归深度" in result.content or "上限" in result.content


@pytest.mark.asyncio
async def test_task_tool_without_supervisor_and_runner_returns_error() -> None:
    """无 supervisor 也无 task_runner → 友好错误。"""
    tool = TaskTool()
    ctx = _make_ctx({}, {"task": "查天气"})
    result = await tool.execute(ctx)
    assert result.is_error


def test_delegate_task_default_policy_restricted() -> None:
    """DEFAULT_POLICY delegate_task 从 deny 改 restricted。"""
    permission = ToolPermission()
    assert permission.check("delegate_task") == "restricted"


@pytest.mark.asyncio
async def test_task_tool_missing_task_description_returns_error() -> None:
    services = _make_supervisor_services(_runner_success)
    tool = TaskTool()
    ctx = _make_ctx(services, {})  # 无 task
    result = await tool.execute(ctx)
    assert result.is_error
    assert "任务描述" in result.content or "task" in result.content.lower()
