"""task 工具: 子 Agent 委派 (限制递归深度和预算)。

J4-2: 迁移到 SubAgentSupervisor, 不再走 task_runner。保留 task + budget_tokens 接口
向后兼容; 内部委托 supervisor.submit() + 等终态 + 返回结果摘要。
递归深度限制 (默认 3) 保留, 防止无限派生。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult
from isac.runtime.subagent.models import SubAgentPolicy, SubAgentTask

if TYPE_CHECKING:
    from isac.runtime.subagent.supervisor import SubAgentSupervisor

# 工具默认等待子任务终态的超时 (秒)
_DEFAULT_WAIT_TIMEOUT = 30.0
_POLL_INTERVAL = 0.05
_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out"})


class TaskTool(Tool):
    @property
    def name(self) -> str:
        return "task"

    @property
    def description(self) -> str:
        return "将子任务委派给一个子 Agent 执行"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "子任务描述"},
                "budget_tokens": {"type": "integer", "description": "子任务 Token 预算 (默认 2000)", "default": 2000},
            },
            "required": ["task"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        # 递归深度检查: services["task_depth"] 由 runtime 维护, 默认 0
        depth = int(context.services.get("task_depth", 0) or 0)
        max_depth = int(context.services.get("task_max_depth", 3) or 3)
        if depth >= max_depth:
            return ToolResult(
                content=f"子任务递归深度已达上限 ({max_depth}), 拒绝继续委派。",
                is_error=True,
            )

        task_text = str(context.args.get("task", "") or "").strip()
        if not task_text:
            return ToolResult(content="task 缺少任务描述。", is_error=True)
        budget = max(500, int(context.args.get("budget_tokens", 2000) or 2000))

        # J4-2: 优先走 SubAgentSupervisor; 无 supervisor 时回退到 task_runner (向后兼容)
        supervisor: SubAgentSupervisor | None = context.services.get("subagent_supervisor")
        if supervisor is not None:
            return await self._delegate_to_supervisor(context, task_text, budget, depth, max_depth)
        # 向后兼容: 旧 task_runner 路径
        runner = context.services.get("task_runner")
        if runner is None:
            return ToolResult(
                content="未配置 SubAgent 运行时, 也未配置 task_runner, 无法委派子 Agent。",
                is_error=True,
            )
        try:
            result = await runner(
                task_text, budget=budget, parent_context=context.agent_context, depth=depth, max_depth=max_depth
            )
        except Exception as exc:
            return ToolResult(content=f"子任务执行失败: {exc}", is_error=True)
        content = str(getattr(result, "content", "") or "")
        if not content:
            return ToolResult(content="子任务未返回内容。")
        return ToolResult(content=f"【子任务结果】\n{content[:4000]}")

    async def _delegate_to_supervisor(
        self, context: ToolContext, objective: str, budget: int, depth: int, max_depth: int
    ) -> ToolResult:
        """委托 supervisor.submit + 等终态 + 返回结果摘要。"""
        supervisor = context.services["subagent_supervisor"]
        agent_ctx = context.agent_context
        task_id = f"sub-{uuid.uuid4().hex[:12]}"
        task = SubAgentTask(
            task_id=task_id,
            parent_agent_id=str(agent_ctx.services.get("agent_id", "") or ""),
            session_id=getattr(agent_ctx.session, "session_id", ""),
            trace_id=str(agent_ctx.services.get("task_id", "") or task_id),
            objective=objective,
            context={"task_depth": depth + 1},
            policy=SubAgentPolicy(max_tokens=budget, max_depth=max_depth),
            created_at=int(time.time()),
        )
        run = await supervisor.submit(task)
        # 子任务派生时 task_depth+1, 递归深度生效
        # (子 Agent 的 services 由 supervisor 注入 runner_factory 时设置 task_depth=depth+1)
        wait_timeout = float(context.args.get("_wait_timeout", _DEFAULT_WAIT_TIMEOUT) or _DEFAULT_WAIT_TIMEOUT)
        deadline = time.monotonic() + wait_timeout
        while time.monotonic() < deadline:
            cur = await supervisor.get_status(task_id, agent_ctx)
            if cur is None:
                break
            if cur.status in _TERMINAL:
                return await self._format_result(task_id, cur, supervisor, agent_ctx)
            await asyncio.sleep(_POLL_INTERVAL)
        cur = await supervisor.get_status(task_id, agent_ctx)
        status = cur.status if cur is not None else run.status
        return ToolResult(
            content=f"子任务仍在执行 (当前状态: {status}, task_id={task_id}), 请稍后用 subagent_status 查询。",
            is_error=False,
        )

    @staticmethod
    async def _format_result(
        task_id: str, run: Any, supervisor: SubAgentSupervisor, agent_ctx: Any
    ) -> ToolResult:
        """格式化终态结果。"""
        if run.status == "succeeded":
            summary = run.result_summary or f"子任务完成 (task_id={task_id})"
            return ToolResult(content=f"【子任务结果】{summary}")
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
            return ToolResult(content=f"子任务已取消 (task_id={task_id})", is_error=False)
        return ToolResult(content=f"子任务 {task_id} 状态: {run.status}")
