"""Tool 基类与上下文 (DEVELOP.md 3.4 / 7.3)。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from isac.core.types import ToolResult
from isac.runtime.services import ServiceContainer
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.core.types import AgentContext

logger = get_logger(__name__)

# U5: tools_policy 合法档位 (未知值 fail-closed 按 deny, 见 ToolPermission.check)。
_VALID_LEVELS: frozenset[str] = frozenset({"allow", "restricted", "ask", "deny"})


@dataclass
class ToolContext:
    """工具执行上下文。

    services 用于注入共享服务 (如 "memory": MemoryRetrievalPipeline,
    "bus": InterAgentBus)，由 runtime 组装时注入，避免工具 import 业务模块。
    Z1-C: 归一化为 ServiceContainer, 工具经宽容属性读取 (缺键 None, 与原 get 同义)。
    """

    args: dict[str, Any]  # LLM 传入的工具参数
    agent_context: AgentContext
    services: ServiceContainer = field(default_factory=ServiceContainer)

    def __post_init__(self) -> None:
        # Z1-C: 裸 dict → ServiceContainer (测试/兼容层可能传裸 dict)。
        if type(self.services) is dict:
            self.services = ServiceContainer(self.services)


class Tool(ABC):
    """工具抽象基类。所有内置/插件工具必须继承此类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一名称 (LLM function calling 名)"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述 (展示给 LLM)"""
        ...

    @property
    def parameters(self) -> dict:
        """JSON Schema 参数定义"""
        return {"type": "object", "properties": {}}

    @abstractmethod
    async def execute(self, context: ToolContext) -> ToolResult:
        """执行工具。失败应抛出 ToolError 或返回 is_error=True 的结果。"""
        ...


class ToolPermission:
    """工具权限检查 (DEVELOP.md 7.3)。

    有效权限 = 全局策略 ∩ Agent 配置 (AgentConfig.tools_policy)。
    """

    DEFAULT_POLICY: dict[str, str] = {
        "send_emoji": "allow",
        "send_image": "allow",
        "query_memory": "allow",
        "query_person_profile": "allow",
        "ask_agent": "allow",
        # M2 Agent Mesh 协作动作: 已接入 MeshActionBroker; restricted 需注入
        # mesh_action_broker + mesh_link_policy 后方可调用 (deny-by-default 仍生效)。
        "notify_agent": "restricted",
        "handoff_conversation": "restricted",
        "list_available_agents": "restricted",
        "memory_query_agent": "restricted",
        # Q0: 默认 deny —— 全仓无搜索后端实现, allow 会让工具出现在 LLM schema
        # 里却恒失败 (LLM 反复调用死工具); 接入后端后在配置中显式开启。
        "web_search": "deny",
        "read_file": "restricted",  # 限制在项目目录内
        "write_file": "restricted",
        "bash": "deny",  # 默认禁用，需在配置中显式启用
        "task": "restricted",  # 限制递归深度和预算
        # J2 语义媒体工具: 默认禁用, 需授权对应模型能力并显式开启 (无真实副作用)
        "generate_image": "deny",
        "generate_video": "deny",
        "transcribe_audio": "deny",
        "synthesize_speech": "deny",
        "understand_image": "deny",
        "understand_video": "deny",
        # J4 SubAgent 工具: 派生默认 restricted (需显式授权); 查询类受限于 Supervisor 注入
        "delegate_task": "restricted",
        "list_subagents": "restricted",
        "subagent_status": "restricted",
        "subagent_log": "restricted",
        "cancel_subagent": "restricted",
    }

    def __init__(self, policy: dict[str, str] | None = None):
        self.policy = {**self.DEFAULT_POLICY, **(policy or {})}

    def check(self, tool_name: str) -> str:
        """返回 "allow" | "restricted" | "ask" | "deny" (未声明默认 allow)。

        U5: 四档语义 —— allow 直接放行; restricted 需注入对应后端服务;
        **ask 执行前需人工审批** (ApprovalGate, 超时 fail-closed); deny 禁用。
        策略表里的未知档位值 fail-closed 归一为 deny (防配置笔误漂移放行)。

        N5b 批次C C9: MCP 桥接工具 (``mcp:`` 前缀) 未显式声明时默认 restricted。
        U0 Fix-87: restricted 语义落实 —— ToolRegistry._required_service 把 mcp:*
        映射到 "mcp_clients" (MCP 接线时 assembly 注入), 未接线的 Agent 缺该服务 →
        restricted 门拒绝 LLM 直调。此前无映射时 restricted 等效 allow (语义矛盾)。
        Agent tools_policy 仍可显式覆盖 (deny 禁用 / allow 放行 / ask 人工审批)。
        """
        if tool_name in self.policy:
            level = self.policy[tool_name]
            if level not in _VALID_LEVELS:
                logger.warning("tools_policy 未知档位, fail-closed 按 deny 处理", tool=tool_name, level=str(level))
                return "deny"
            return level
        if tool_name.startswith("mcp:"):
            return "restricted"
        return "allow"
