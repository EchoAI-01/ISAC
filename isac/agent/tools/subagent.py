"""J4 SubAgent 工具 (SPECIFICATION.md 2.5)。

Agent 用 delegate_task 把需要调用工具或查询的子任务交给隔离子 Agent, 自己只收到结构化
结果; 并可用 list/status/log/cancel 追溯子任务。主 Agent 默认只收到 SubAgentResult,
完整脱敏日志按 task_id 显式查询。

J4-2: delegate_task 真实链路落地。构造 SubAgentTask → supervisor.submit() → 等终态
→ 返回结果摘要给 LLM。等待超时返回当前状态 (不阻塞主链路)。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import AgentContext, ToolResult
from isac.runtime.subagent.models import SubAgentPolicy, SubAgentTask

if TYPE_CHECKING:
    from isac.runtime.subagent.supervisor import SubAgentSupervisor

# 工具默认等待子任务终态的超时 (秒); 超时返回当前状态, 不阻塞主链路
_DEFAULT_WAIT_TIMEOUT = 30.0
# 工具 poll 间隔
_POLL_INTERVAL = 0.05

_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out"})


class _SupervisorToolBase(Tool):
    """SubAgent 工具公共骨架: 统一从 services 取 Supervisor。"""

    @staticmethod
    def _supervisor(context: ToolContext) -> SubAgentSupervisor | None:
        return context.services.get("subagent_supervisor")


class DelegateTaskTool(_SupervisorToolBase):
    @property
    def name(self) -> str:
        return "delegate_task"

    @property
    def description(self) -> str:
        return "把需要调用工具或查询的子任务交给隔离子 Agent 执行, 只返回结果"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "objective": {"type": "string", "description": "子任务目标"},
                "summary": {"type": "string", "description": "给子 Agent 的最小背景摘要"},
            },
            "required": ["objective"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        supervisor = self._supervisor(context)
        if supervisor is None:
            return ToolResult(content="未配置 SubAgent 运行时, 无法派生子任务。", is_error=True)

        objective = str(context.args.get("objective", "") or "").strip()
        if not objective:
            return ToolResult(content="缺少 objective, 无法派生子任务。", is_error=True)

        summary = str(context.args.get("summary", "") or "")
        # 构造 SubAgentTask
        agent_ctx = context.agent_context
        task_id = f"sub-{uuid.uuid4().hex[:12]}"
        task = SubAgentTask(
            task_id=task_id,
            parent_agent_id=str(agent_ctx.services.get("agent_id", "") or ""),
            session_id=getattr(agent_ctx.session, "session_id", ""),
            trace_id=str(agent_ctx.services.get("task_id", "") or task_id),
            objective=objective,
            context={"summary": summary},
            policy=SubAgentPolicy(),  # 默认策略; J4 后续接入父/Channel/全局交集
            created_at=int(time.time()),
        )
        # submit → 等终态 → 返回摘要
        run = await supervisor.submit(task)
        wait_timeout = float(context.args.get("_wait_timeout", _DEFAULT_WAIT_TIMEOUT) or _DEFAULT_WAIT_TIMEOUT)
        # 等待终态 (poll get_status)
        deadline = time.monotonic() + wait_timeout
        while time.monotonic() < deadline:
            cur = await supervisor.get_status(task_id, agent_ctx)
            if cur is None:
                break
            if cur.status in _TERMINAL:
                return await self._format_terminal_result(task_id, cur, supervisor, agent_ctx)
            await asyncio.sleep(_POLL_INTERVAL)
        # 超时: 返回当前状态 (不取消, 后台 task 继续; LLM 可后续 status 查询)
        cur = await supervisor.get_status(task_id, agent_ctx)
        status = cur.status if cur is not None else run.status
        return ToolResult(
            content=f"子任务 {task_id} 仍在执行 (当前状态: {status}), 请稍后用 subagent_status 查询。",
            is_error=False,
        )

    @staticmethod
    async def _format_terminal_result(
        task_id: str, run: Any, supervisor: SubAgentSupervisor, agent_ctx: AgentContext  # type: ignore[name-defined]
    ) -> ToolResult:
        """格式化终态结果给 LLM (优先从 run.result_summary 取, journal 作为补充)。"""
        if run.status == "succeeded":
            summary = run.result_summary or f"子任务完成 (task_id={task_id})"
            return ToolResult(content=summary, is_error=False)
        if run.status == "failed":
            return ToolResult(
                content=f"子任务失败: {run.error_summary or '未知错误'} (task_id={task_id})",
                is_error=True,
            )
        if run.status == "timed_out":
            return ToolResult(
                content=f"子任务超时 (task_id={task_id}, code={run.error_code})",
                is_error=True,
            )
        if run.status == "cancelled":
            return ToolResult(
                content=f"子任务已取消 (task_id={task_id})",
                is_error=False,
            )
        return ToolResult(content=f"子任务 {task_id} 状态: {run.status}", is_error=False)


class ListSubagentsTool(_SupervisorToolBase):
    @property
    def name(self) -> str:
        return "list_subagents"

    @property
    def description(self) -> str:
        return "列出当前子任务及其状态"

    async def execute(self, context: ToolContext) -> ToolResult:
        supervisor = self._supervisor(context)
        if supervisor is None:
            return ToolResult(content="未配置 SubAgent 运行时。", is_error=True)
        runs = await supervisor.list_runs(context.agent_context, {})
        if not runs:
            return ToolResult(content="当前没有子任务。")
        lines = [f"- {run.task_id}: {run.status}" for run in runs]
        return ToolResult(content="\n".join(lines))


class SubagentStatusTool(_SupervisorToolBase):
    @property
    def name(self) -> str:
        return "subagent_status"

    @property
    def description(self) -> str:
        return "查询某个子任务的运行状态"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "子任务 ID"}},
            "required": ["task_id"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        supervisor = self._supervisor(context)
        if supervisor is None:
            return ToolResult(content="未配置 SubAgent 运行时。", is_error=True)
        task_id = str(context.args.get("task_id", "") or "").strip()
        if not task_id:
            return ToolResult(content="缺少 task_id。", is_error=True)
        run = await supervisor.get_status(task_id, context.agent_context)
        if run is None:
            return ToolResult(content=f"未找到子任务 {task_id}。", is_error=True)
        return ToolResult(content=f"子任务 {task_id} 状态: {run.status}")


class SubagentLogTool(_SupervisorToolBase):
    @property
    def name(self) -> str:
        return "subagent_log"

    @property
    def description(self) -> str:
        return "分页读取某个子任务的脱敏工作日志"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "子任务 ID"},
                "after_seq": {"type": "integer", "description": "从该序号之后读取", "default": 0},
            },
            "required": ["task_id"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        supervisor = self._supervisor(context)
        if supervisor is None:
            return ToolResult(content="未配置 SubAgent 运行时。", is_error=True)
        task_id = str(context.args.get("task_id", "") or "").strip()
        if not task_id:
            return ToolResult(content="缺少 task_id。", is_error=True)
        after_seq = int(context.args.get("after_seq", 0) or 0)
        events = await supervisor.fetch_log(task_id, after_seq, 50, context.agent_context)
        if not events:
            return ToolResult(content=f"子任务 {task_id} 暂无更多日志。")
        lines = [f"[{event.seq}] {event.event_type}: {event.summary}" for event in events]
        return ToolResult(content="\n".join(lines))


class CancelSubagentTool(_SupervisorToolBase):
    @property
    def name(self) -> str:
        return "cancel_subagent"

    @property
    def description(self) -> str:
        return "取消一个进行中的子任务 (幂等)"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "子任务 ID"}},
            "required": ["task_id"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        supervisor = self._supervisor(context)
        if supervisor is None:
            return ToolResult(content="未配置 SubAgent 运行时。", is_error=True)
        task_id = str(context.args.get("task_id", "") or "").strip()
        if not task_id:
            return ToolResult(content="缺少 task_id。", is_error=True)
        run = await supervisor.cancel(task_id, context.agent_context)
        if run is None:
            return ToolResult(content=f"未找到子任务 {task_id}。", is_error=True)
        return ToolResult(content=f"子任务 {task_id} 当前状态: {run.status}")
