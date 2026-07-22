"""task 工具: 子 Agent 委派 (限制递归深度和预算)。

经 services["task_runner"] 派生子 Agent 执行子任务; 未注入时返回友好错误。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


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
        runner = context.services.get("task_runner")
        if runner is None:
            return ToolResult(content="未配置 task_runner, 无法委派子 Agent。", is_error=True)

        task_text = str(context.args.get("task", "") or "").strip()
        if not task_text:
            return ToolResult(content="task 缺少任务描述。", is_error=True)
        budget = max(500, int(context.args.get("budget_tokens", 2000) or 2000))

        # 递归深度检查: services["task_depth"] 由 runtime 维护, 默认 0
        depth = int(context.services.get("task_depth", 0) or 0)
        max_depth = int(context.services.get("task_max_depth", 3) or 3)
        if depth >= max_depth:
            return ToolResult(
                content=f"子任务递归深度已达上限 ({max_depth}), 拒绝继续委派。",
                is_error=True,
            )

        try:
            result = await runner(task_text, budget=budget, parent_context=context.agent_context)
        except Exception as exc:
            return ToolResult(content=f"子任务执行失败: {exc}", is_error=True)

        content = str(getattr(result, "content", "") or "")
        if not content:
            return ToolResult(content="子任务未返回内容。")
        return ToolResult(content=f"【子任务结果】\n{content[:4000]}")
