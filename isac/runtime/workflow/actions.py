"""Workflow action_handler / condition_evaluator 生产注入 (S5, DEVELOPMENT_PLAN.md §四 P5/O3)。

S5 激活: 把已实现的 WorkflowEngine 的 Stage.action 真正路由到生产后端:
- ``"tool:<tool_name>"`` 前缀 → 经 AgentManager 拿到目标 Agent 的 ToolRegistry,
  构造最小 AgentContext 调 ``ToolRegistry.execute`` (ToolCall.arguments 取自
  ``stage.params``; AgentContext.session/user_profile/current_message 用最小
  stub 构造, 服务于工具内部对 services 的访问)。
- 未知/无前缀的 action → 记 warning 并视为 noop (不抛异常, 避免不可恢复的
  action 名字白白重试 max_retries 次; 真正失败的工具调用自身会 return
  ToolResult(is_error=True), 不会触发 Stage 重试)。

condition_evaluator: 一个极简 DSL, 与 WorkflowEngine._evaluate 的默认行为等价
(空字符串/"true"/"1" 为真, 其余为假), 作为后续扩展点。

不实现 "Agent 主动触发 workflow 的工具入口" (HANDOFF 明确为 P5 决策项, 有意
未做, 避免半接线死代码)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from isac.core.types import AgentContext, ToolCall
from isac.gateway.models import Session
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.runtime.workflow.engine import ActionHandler, ConditionEvaluator

logger = get_logger(__name__)

_TOOL_PREFIX = "tool:"
_AGENT_PREFIX = "agent:"

# stage.params 里可选的 agent_id 字段名 (用于 tool: 路由时定位目标 Agent)
_STAGE_PARAM_AGENT_ID = "agent_id"


def build_default_action_handler(
    agent_manager_resolver: Any,
) -> ActionHandler:
    """构造生产 action_handler (传入 agent_manager 或一个 resolver callable)。

    agent_manager_resolver: ``Callable[[str], Awaitable[AgentInstance | None]]``
    或 AgentManager 实例 (内部用 ``await resolver.get(agent_id)`` 取实例)。
    """

    async def handler(stage: Any) -> None:
        action = str(getattr(stage, "action", "") or "").strip()
        if not action:
            return  # 空 action 视为 noop
        params = dict(getattr(stage, "params", {}) or {})
        if action.startswith(_TOOL_PREFIX):
            tool_name = action[len(_TOOL_PREFIX):]
            await _invoke_tool(agent_manager_resolver, stage, tool_name, params)
            return
        if action.startswith(_AGENT_PREFIX):
            # agent:<id>:<intent> 形式暂未实现真实路由 (留作 P5 Agent 工具入口),
            # 当前记 warning noop, 不抛异常阻塞工作流。
            logger.warning(
                "workflow stage action=agent:* 暂未实现真实路由, 视为 noop",
                stage_id=getattr(stage, "stage_id", ""), action=action,
            )
            return
        logger.warning(
            "workflow stage action 未知前缀, 视为 noop (不触发重试)",
            stage_id=getattr(stage, "stage_id", ""), action=action,
        )

    return handler


async def _invoke_tool(
    agent_manager_resolver: Any,
    stage: Any,
    tool_name: str,
    params: dict,
) -> None:
    """经 agent_manager 取目标 Agent 的 ToolRegistry.execute 执行工具。

    失败 (Agent 不存在/工具不存在/工具 execute 异常) 抛异常让 Stage 走重试
    机制 (与"未知 action noop 不重试"的语义相反——明确的 tool 调用失败应被重试)。
    """
    agent_id = str(params.get(_STAGE_PARAM_AGENT_ID, "") or "").strip()
    if not agent_id:
        raise ValueError(
            f"workflow stage {getattr(stage, 'stage_id', '')} action=tool:{tool_name} "
            f"缺少 {_STAGE_PARAM_AGENT_ID} 参数, 无法定位目标 Agent"
        )
    instance = await _resolve_agent_instance(agent_manager_resolver, agent_id)
    if instance is None:
        raise ValueError(f"workflow 目标 Agent 不存在: {agent_id}")
    tools = getattr(instance, "tools", None)
    if tools is None:
        raise ValueError(f"workflow 目标 Agent 无 ToolRegistry: {agent_id}")
    services = getattr(instance, "services", {}) or {}
    tool_call = ToolCall(id=f"wf-{getattr(stage, 'stage_id', '')}", name=tool_name, arguments=params)
    ctx = _build_minimal_agent_context(agent_id, params)
    result = await tools.execute(tool_call, ctx, services)
    if getattr(result, "is_error", False):
        raise RuntimeError(f"工具 {tool_name} 执行失败: {getattr(result, 'content', '')}")


async def _resolve_agent_instance(agent_manager_resolver: Any, agent_id: str) -> Any:
    """从 resolver 取 AgentInstance (兼容 AgentManager 实例与直接 callable)。"""
    getter = getattr(agent_manager_resolver, "get", None)
    if callable(getter):
        return await getter(agent_id)
    if callable(agent_manager_resolver):
        return await agent_manager_resolver(agent_id)
    return None


def _build_minimal_agent_context(agent_id: str, params: dict) -> AgentContext:
    """构造最小 AgentContext 供 ToolRegistry.execute 使用。

    Session/ISACMessage 用最小 stub, 服务于工具内部对 services 的访问
    (大多数工具不直接依赖 session 字段)。需真实 session 的工具 (如 fetch_history)
    会失败并走 Stage 重试机制。
    """
    from isac.channel.model import ISACMessage

    session = Session(session_id=str(params.get("session_id") or "workflow-stub"), user_id="workflow")
    msg = ISACMessage(
        msg_id="", platform="workflow", timestamp=0, user_id="workflow",
        user_name="workflow", content="",
    )
    return AgentContext(
        session=session,
        user_profile=None,
        current_message=msg,
        timestamp=0.0,
    )


def build_default_condition_evaluator() -> ConditionEvaluator:
    """构造生产 condition_evaluator (与 WorkflowEngine._evaluate 默认等价的占位 DSL)。

    空字符串 / "true" / "1" (不区分大小写) 视为真; "false" / "0" / 其他视为假。
    仅作为扩展点: 真实业务若需复杂表达式可注入自定义 evaluator。
    """

    def evaluator(condition: str) -> bool:
        c = (condition or "").strip().lower()
        if not c or c in ("true", "1", "yes"):
            return True
        if c in ("false", "0", "no"):
            return False
        # 未识别的非空字符串默认为 False (保守, 避免误执行 conditional stage)
        return False

    return evaluator
