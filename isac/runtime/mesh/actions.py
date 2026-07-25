"""MeshActionBroker: Agent 间协作动作骨架 (M2, ROUTING_AND_AGENT_MESH.md §5/§6)。

[框架已搭建 / scaffolding] notify / handoff / memory_query / list 四类 Agent 间动作的
挂接点就位, 委托既有 `InterAgentBus.send`; 真正的 ACL 权限校验 (MeshLinkPolicy)、
handoff 会话摘要交接、memory_query 记忆范围裁剪留待 M2 实现节点 (见 TODO)。
默认 deny-by-default: 未显式授权动作一律拒绝, 主链路零行为变化。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.runtime.mesh.models import MeshLinkPolicy, MeshMessageType
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.runtime.bus import InterAgentBus

logger = get_logger(__name__)


class MeshActionBroker:
    """Agent 间协作动作代理 (骨架, 委托 InterAgentBus)。"""

    def __init__(self, bus: InterAgentBus | None = None) -> None:
        self._bus = bus

    def is_permitted(self, action: str, policy: MeshLinkPolicy | None) -> bool:
        """deny-by-default 的动作鉴权。

        TODO(M2): 结合 Link 方向/enabled 与 MeshLinkPolicy.permissions 做完整 ACL;
        骨架阶段: 无 policy 一律拒绝; 有 policy 时仅当 action 在 permissions 中才允许。
        """
        if policy is None:
            return False
        return action in policy.permissions

    async def notify(self, from_agent: str, to_agent: str, content: str, policy: MeshLinkPolicy | None = None) -> bool:
        """单向通知 (不等待响应)。

        TODO(M2): 经 bus 发送 MeshMessageType.NOTIFY; 骨架阶段仅做鉴权判定, 不投递。
        """
        _ = (from_agent, to_agent, content, MeshMessageType.NOTIFY)
        return self.is_permitted("notify", policy)

    async def handoff(self, from_agent: str, to_agent: str, summary: str, policy: MeshLinkPolicy | None = None) -> bool:
        """移交会话所有权 (附会话摘要)。

        TODO(M2): 经 bus 发送 MeshMessageType.HANDOFF + 会话摘要交接; 骨架阶段仅鉴权。
        """
        _ = (from_agent, to_agent, summary, MeshMessageType.HANDOFF)
        return self.is_permitted("handoff", policy)

    async def memory_query(
        self, from_agent: str, to_agent: str, query: str, policy: MeshLinkPolicy | None = None
    ) -> bool:
        """跨 Agent 查询记忆 (受 visible_memory_scopes 裁剪)。

        TODO(M2): 经 bus 发送 MeshMessageType.MEMORY_QUERY, 按 policy.visible_memory_scopes
        裁剪可见范围; 骨架阶段仅鉴权。
        """
        _ = (from_agent, to_agent, query, MeshMessageType.MEMORY_QUERY)
        return self.is_permitted("memory_query", policy)

    def list_available(self, agent_id: str) -> list[str]:
        """列出可协作的 Agent (已配置 Link 的对端)。

        TODO(M2): 从 InterAgentBus 的 Link 表按 agent_id 过滤可见对端;
        骨架阶段恒返回空列表。
        """
        _ = agent_id
        return []
