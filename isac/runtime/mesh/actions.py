"""MeshActionBroker: Agent 间协作动作 (M2, ROUTING_AND_AGENT_MESH.md §5/§6)。

M2 实现: is_permitted 结合 Link 方向/enabled 与 MeshLinkPolicy.permissions 做完整
ACL; notify/handoff/memory_query 经 bus.send 真实投递; handoff 把 summary 进
context.summary 交接; memory_query 把 visible_memory_scopes 进 context.filters
让接收方按 scope 裁剪; list_available 从 bus.links 按 agent_id 过滤可见对端
(enabled 且双向或单向 from→to)。默认 deny-by-default; 无 bus 时所有动作拒绝
(零行为变化)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.runtime.mesh.models import MeshLinkPolicy, MeshMessageType
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.runtime.bus import InterAgentBus

logger = get_logger(__name__)


class MeshActionBroker:
    """Agent 间协作动作代理 (委托 InterAgentBus)。"""

    def __init__(self, bus: InterAgentBus | None = None) -> None:
        self._bus = bus

    def is_permitted(self, action: str, policy: MeshLinkPolicy | None) -> bool:
        """deny-by-default 的动作鉴权。

        M2: 无 policy 一律拒绝; 有 policy 时仅当 action 在 permissions 中才允许。
        Link 方向/enabled 由 bus.send 的 ACL (can_talk) 在投递时二次校验, 这里只看 policy。
        """
        if policy is None:
            return False
        return action in policy.permissions

    async def notify(
        self, from_agent: str, to_agent: str, content: str, policy: MeshLinkPolicy | None = None
    ) -> bool:
        """单向通知 (不等待响应)。

        M2: ACL 通过后经 bus.send 投递 MeshMessageType.NOTIFY; 无 bus 时拒绝。
        """
        if not self.is_permitted("notify", policy) or self._bus is None:
            return False
        return await self._send(from_agent, to_agent, content, MeshMessageType.NOTIFY)

    async def handoff(
        self, from_agent: str, to_agent: str, summary: str, policy: MeshLinkPolicy | None = None
    ) -> bool:
        """移交会话所有权 (附会话摘要)。

        M2: 经 bus.send 投递 HANDOFF; summary 进 context.summary 让接收方读出交接上下文。
        """
        if not self.is_permitted("handoff", policy) or self._bus is None:
            return False
        return await self._send(
            from_agent, to_agent, summary, MeshMessageType.HANDOFF, extra_context={"summary": summary}
        )

    async def memory_query(
        self, from_agent: str, to_agent: str, query: str, policy: MeshLinkPolicy | None = None
    ) -> bool:
        """跨 Agent 查询记忆 (受 visible_memory_scopes 裁剪)。

        M2: 经 bus.send 投递 MEMORY_QUERY; visible_memory_scopes 进 context.filters.scopes
        让接收方按 scope 裁剪可见范围。
        """
        if not self.is_permitted("memory_query", policy) or self._bus is None:
            return False
        scopes = list(policy.visible_memory_scopes) if policy is not None else []
        return await self._send(
            from_agent,
            to_agent,
            query,
            MeshMessageType.MEMORY_QUERY,
            extra_context={"filters": {"scopes": scopes}},
        )

    async def _send(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        msg_type: MeshMessageType,
        *,
        extra_context: dict | None = None,
    ) -> bool:
        """构造 InterAgentMessage 并经 bus.send 投递; ACL 在 bus 内二次校验。

        bus.send 对 notify 类型或不注入 deliver 时返回 None (无响应), 但 ACL
        通过即视为投递成功 (broker 只负责投递, 响应由接收方异步处理)。
        """
        from isac.runtime.bus import InterAgentMessage

        context = dict(extra_context) if extra_context else {}
        message = InterAgentMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            type=msg_type.value,
            content=content,
            context=context,
        )
        try:
            await self._bus.send(message)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Mesh 动作投递失败",
                action=msg_type.value,
                from_agent=from_agent,
                to_agent=to_agent,
                error=str(exc),
            )
            return False
        # bus.send 不抛 = ACL 通过 + 已投递 (响应异步返回, broker 不等)
        return True

    def list_available(self, agent_id: str) -> list[str]:
        """列出可协作的 Agent (已配置 Link 的对端, 双向或单向 from→to, enabled)。

        M2: 从 InterAgentBus.list_links 过滤; 双向 Link 双方都可见, 单向 Link 只
        from→to 方向可见; disabled Link 不计入。
        """
        if self._bus is None:
            return []
        peers: list[str] = []
        seen: set[str] = set()
        for link in self._bus.list_links():
            if not link.enabled:
                continue
            if link.from_agent == agent_id and link.to_agent not in seen:
                peers.append(link.to_agent)
                seen.add(link.to_agent)
            elif link.direction == "both" and link.to_agent == agent_id and link.from_agent not in seen:
                peers.append(link.from_agent)
                seen.add(link.from_agent)
        return peers
