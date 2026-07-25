"""生产 SubAgent runner：用独立上下文和收窄工具执行临时任务。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from isac.agent.hooks import AgentHooks
from isac.agent.injectors.base_identity import BaseIdentityInjector
from isac.agent.loop import ISACAgentLoop
from isac.agent.prompt_builder import SystemPromptBuilder
from isac.agent.tools.base import ToolPermission
from isac.agent.tools.registry import ToolRegistry
from isac.channel.model import ISACMessage
from isac.core.types import AgentContext, Budget
from isac.gateway.models import Session
from isac.runtime.subagent.models import SubAgentResult, SubAgentTask

if TYPE_CHECKING:
    from isac.runtime.manager import AgentManager
    from isac.runtime.subagent.supervisor import SubAgentSupervisor

_CHANNEL_TOOLS = frozenset({"send_emoji", "send_image", "switch_chat"})
_DELEGATION_TOOLS = frozenset({"task", "delegate_task"})
_TOOL_SERVICE_KEYS: dict[str, tuple[str, ...]] = {
    "query_memory": ("memory",),
    "query_person_profile": ("memory",),
    "fetch_history": ("channel_history",),
    "read_file": ("workspace_root",),
    "web_search": ("web_search",),
}


def configure_subagent_runner(supervisor: SubAgentSupervisor, manager: AgentManager) -> None:
    """把生产 runner 绑定到 Supervisor；调用方负责先创建 AgentManager。"""

    async def _runner(task: SubAgentTask) -> SubAgentResult:
        instance = await manager.get(task.parent_agent_id)
        if instance is None or instance.status != "running":
            raise RuntimeError(f"父 Agent 不存在或未运行: {task.parent_agent_id}")

        tools = _build_tool_registry(instance.tools, task)
        services = _build_services(instance.services, task)
        prompt_builder = SystemPromptBuilder()
        prompt_builder.register(
            BaseIdentityInjector(
                "你是隔离的事务型子 Agent。只完成给定任务，返回简洁、可核验的结果；"
                "不得假装拥有主会话历史、关系状态或未授权能力。"
            )
        )
        loop = ISACAgentLoop(
            llm=instance.loop.llm,
            prompt_builder=prompt_builder,
            hooks=AgentHooks(),
            tools=tools,
            provider_manager=instance.loop.provider_manager,
            services=services,
        )
        message = ISACMessage(
            msg_id=f"subagent:{task.task_id}",
            platform="subagent",
            timestamp=int(time.time()),
            user_id=task.parent_agent_id,
            user_name="",
            group_id=None,
            content=task.objective,
        )
        session = Session(
            session_id=f"subagent:{task.task_id}",
            user_id=task.parent_agent_id,
            agent_id=task.parent_agent_id,
            platform="subagent",
        )
        context = AgentContext(
            session=session,
            user_profile=None,
            current_message=message,
            budget=Budget(
                max_iterations=max(1, task.policy.max_tool_calls + 1),
                remaining_iterations=max(1, task.policy.max_tool_calls + 1),
                max_tokens=task.policy.max_tokens,
            ),
            services={
                "agent_id": task.parent_agent_id,
                "task_id": task.task_id,
                "task_depth": int(task.context.get("task_depth", 0)),
                "task_max_depth": task.policy.max_depth,
            },
        )
        result = await loop.run([{"role": "user", "content": task.objective}], context)
        status = "succeeded" if not result.stopped_by_budget else "failed"
        summary = result.content or "子任务预算耗尽，未产生结果"
        return SubAgentResult(
            task_id=task.task_id,
            status=status,
            summary=summary,
            usage=_usage(context),
            completed_at=int(time.time()),
        )

    supervisor.set_runner_factory(_runner)


def _build_tool_registry(parent: ToolRegistry, task: SubAgentTask) -> ToolRegistry:
    allowed = set(task.policy.allowed_tools)
    if not task.policy.allow_channel_send:
        allowed -= _CHANNEL_TOOLS
    if not task.policy.allow_delegate:
        allowed -= _DELEGATION_TOOLS
    registry = ToolRegistry(ToolPermission({name: "allow" for name in allowed}))
    for name in sorted(allowed):
        tool = parent.get(name)
        if tool is not None:
            registry.register(tool)
    return registry


def _build_services(parent_services: dict[str, Any], task: SubAgentTask) -> dict[str, Any]:
    keys: set[str] = set()
    for tool_name in task.policy.allowed_tools:
        keys.update(_TOOL_SERVICE_KEYS.get(tool_name, ()))
    if not task.policy.readable_memory_scopes:
        keys.discard("memory")
    return {key: parent_services[key] for key in keys if key in parent_services}


def _usage(context: AgentContext):
    from isac.core.types import TokenUsage

    return TokenUsage(total_tokens=context.budget.used_tokens)
