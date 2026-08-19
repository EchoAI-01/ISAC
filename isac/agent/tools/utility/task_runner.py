"""task 工具的子 Agent 委派 runner (H3)。

接收 task 描述与预算, 用 ISACAgentLoop 派生子任务执行, 限制递归深度。
实现 task_runner 服务供 TaskTool 调用。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
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
        depth: int = 0,
        max_depth: int = 3,
    ) -> ToolResult:
        """执行子任务, 返回 ToolResult。

        Fix-34: 递归深度由调用方 (TaskTool, 已从其 AgentContext.services 的
        `task_depth` 键读出)
        显式传入, 不再从 self._loop.services 读写。self._loop 是宿主 Agent
        全生命周期共享的单个 loop 实例——它的 services 字典也随之在同一 Agent
        的所有会话间共享 (非并发安全的按次调用状态), 之前若往里写 task_depth,
        并发的其他会话/嵌套调用会读到彼此的深度值, 递归限制形同虚设。

        子任务改用**独立构造**的 ISACAgentLoop 实例执行 (复用宿主 loop 的
        llm/prompt_builder/hooks/tools/provider_manager, 只替换 services 为
        一份带正确 task_depth 的浅拷贝), 而不是直接复用 self._loop——避免任何
        写 task_depth 的尝试污染同一 Agent 下并发的其他调用, 与
        SubAgentSupervisor 生产 runner (isac/runtime/subagent/runner.py) 每个
        子任务都拿到全新 loop 实例的隔离方式一致。
        """
        if depth >= max_depth:
            return ToolResult(
                content=f"子任务递归深度已达上限 ({max_depth}), 拒绝继续委派。",
                is_error=True,
            )
        # 简化: 用 budget 限制子任务 token 数, parent_context 的 budget 独立
        child_budget = max(500, min(budget, self.default_budget))
        logger.info(
            "子任务派发",
            task_preview=task[:80],
            budget=child_budget,
            depth=depth,
        )
        # 构造子任务上下文与独立 loop 实例
        from isac.agent.loop import ISACAgentLoop
        from isac.core.types import Budget

        child_context = AgentContext(
            session=parent_context.session,
            user_profile=parent_context.user_profile,
            current_message=parent_context.current_message,
            budget=Budget(max_tokens=child_budget, max_iterations=10),
        )
        child_services = {
            **self._loop.services,
            "task_depth": depth + 1,
            "task_max_depth": max_depth,
        }
        child_loop = ISACAgentLoop(
            llm=self._loop.llm,
            prompt_builder=self._loop.prompt_builder,
            hooks=self._loop.hooks,
            tools=self._loop.tools,
            provider_manager=self._loop.provider_manager,
            services=child_services,
        )
        messages = [
            {"role": "system", "content": "你是子任务执行者, 完成用户委派的子任务, 输出简洁结果。"},
            {"role": "user", "content": task},
        ]
        try:
            result = await child_loop.run(messages, child_context)
        except Exception as exc:  # noqa: BLE001
            logger.warning("子任务执行失败", error=str(exc))
            return ToolResult(content=f"子任务执行失败: {exc}", is_error=True)
        return ToolResult(content=result.content or "(子任务无输出)")


def make_task_runner(loop: ISACAgentLoop) -> Callable[..., Awaitable[ToolResult]]:
    """工厂: 用 Agent Loop 构造 TaskRunner (供服务袋 `task_runner` 键注入)。

    Fix-34: 返回 TaskRunner.run 的绑定方法, 而不是 TaskRunner 实例本身——
    调用方 (TaskTool) 把 `task_runner` 服务当作可直接调用的函数使用
    (``runner(task, budget=..., parent_context=..., depth=..., max_depth=...)``),
    TaskRunner 没有实现 __call__, 裸实例传过去会在调用时报
    "'TaskRunner' object is not callable"。
    """
    return TaskRunner(loop).run
