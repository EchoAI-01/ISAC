"""路由数据模型 (SPECIFICATION.md 1.7)。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ChannelBinding:
    """显式绑定: 某平台某会话固定归属某 Agent (路由优先级最高)"""

    platform: str
    agent_id: str
    group_id: str | None = None  # 与 user_id 都为 None 表示整个平台
    user_id: str | None = None


@dataclass
class RoutingRules:
    """路由规则集 (data/routing.jsonc, 控制面可热更新)"""

    bindings: list[ChannelBinding] = field(default_factory=list)
    default_agents: dict[str, str] = field(default_factory=dict)  # platform -> agent_id
    # trigger_words 在各 AgentConfig 中定义 (经 AgentRoutingInfo 注入)


@dataclass
class RoutingDecision:
    """路由结果"""

    agent_id: str
    matched_by: str  # "binding" | "trigger_word" | "default"
    content: str  # 剥离触发词后的内容


class AgentRoutingInfo(Protocol):
    """路由所需的 Agent 信息 (由 runtime 注入，避免 router 依赖 runtime)"""

    @property
    def agent_id(self) -> str: ...

    @property
    def trigger_words(self) -> list[str]: ...


# 返回所有可路由 Agent 的路由信息
AgentsProvider = Callable[[], list[AgentRoutingInfo]]
