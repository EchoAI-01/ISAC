"""task 工具的子 Agent 委派 runner (H3)。

接收 task 描述与预算, 用 ISACAgentLoop 派生子任务执行, 限制递归深度。
实现 task_runner 服务供 TaskTool 调用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.core.types import AgentContext, ToolResult
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.agent.loop import ISACAgentLoop

logger = get_logger(__name__)


class TaskRunner:
    """子 Agent 委派 runner: 用主 Agent Loop 派生子任务, 限制递归深度。"""

    def __init__(self, loop: ISACAgentLoop, *, default_budget: int = 2000):
        self._loop = loop
        self.default_budget = default_budget

    async def run(
        self,
        task: str,
        *,
        budget: int,
        parent_context: AgentContext,
    ) -> ToolResult:
        """执行子任务, 返回 ToolResult。

        递归深度由 services["task_depth"] 控制 (主调用为 0, 嵌套调用 +1)。
        """
        current_depth = int(parent_context.budget.remaining_iterations) if parent_context else 0
        # 简化: 用 budget 限制子任务 token 数, parent_context 的 budget 独立
        child_budget = max(500, min(budget, self.default_budget))
        logger.info(
            "子任务派发",
            task_preview=task[:80],
            budget=child_budget,
            parent_depth=current_depth,
        )
        # 构造子任务上下文
        from isac.core.types import Budget

        child_context = AgentContext(
            session=parent_context.session,
            user_profile=parent_context.user_profile,
            current_message=parent_context.current_message,
            budget=Budget(max_tokens=child_budget, max_iterations=10),
        )
        messages = [
            {"role": "system", "content": "你是子任务执行者, 完成用户委派的子任务, 输出简洁结果。"},
            {"role": "user", "content": task},
        ]
        try:
            result = await self._loop.run(messages, child_context)
        except Exception as exc:  # noqa: BLE001
            logger.warning("子任务执行失败", error=str(exc))
            return ToolResult(content=f"子任务执行失败: {exc}", is_error=True)
        return ToolResult(content=result.content or "(子任务无输出)")


def make_task_runner(loop: ISACAgentLoop) -> TaskRunner:
    """工厂: 用 Agent Loop 构造 TaskRunner (供 services["task_runner"] 注入)。"""
    return TaskRunner(loop)
