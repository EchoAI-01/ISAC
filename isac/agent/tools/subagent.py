"""J4 SubAgent 工具桩 (SPECIFICATION.md 2.5)。

Agent 用 delegate_task 把需要调用工具或查询的子任务交给隔离子 Agent, 自己只收到结构化
结果; 并可用 list/status/log/cancel 追溯子任务。主 Agent 默认只收到 SubAgentResult,
完整脱敏日志按 task_id 显式查询。

骨架状态: 工具契约与 Supervisor 接缝就位; delegate 默认 deny 且执行循环留待 J4 实现节点,
查询/取消类委托 Supervisor。这些工具默认不在 assembly 注册, 待 J4 实现节点按授权接入。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class _SupervisorToolBase(Tool):
    """SubAgent 工具公共骨架: 统一从 services 取 Supervisor。"""

    @staticmethod
    def _supervisor(context: ToolContext):  # noqa: ANN205
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
        if self._supervisor(context) is None:
            return ToolResult(content="未配置 SubAgent 运行时, 无法派生子任务。", is_error=True)
        # TODO(J4): 构造 SubAgentTask + ContextEnvelope, submit 并等待 / 回投 SubAgentResult。
        return ToolResult(content="子 Agent 执行能力尚未接入 (J4 实现节点补齐)。", is_error=True)


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
