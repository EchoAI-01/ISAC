"""MeshActionBroker: Agent 间协作动作 (M2, ROUTING_AND_AGENT_MESH.md §5/§6)。

M2 实现: is_permitted 结合 Link 方向/enabled 与 MeshLinkPolicy.permissions 做完整
ACL; notify/handoff/memory_query 经 bus.send 真实投递; handoff 把 summary 进
context.summary 交接; memory_query 把 visible_memory_scopes 进 context.filters
让接收方按 scope 裁剪; list_available 从 bus.links 按 agent_id 过滤可见对端
(enabled 且双向或单向 from→to)。默认 deny-by-default; 无 bus 时所有动作拒绝
(零行为变化)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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

    def policy_for(self, from_agent: str, to_agent: str) -> MeshLinkPolicy | None:
        """P2: 从 (from, to) 对应的 enabled Link 解析出该链路的策略; 无 Link 返回 None。

        此前工具从 services["mesh_link_policy"] 取**单值**策略, 与"每条 Link 一套
        权限"的现实不匹配 (且生产无人注入 → 恒 None → 全部拒绝)。现在策略随
        Link 配置 (links.jsonc / 控制面 POST /links), 按对端解析。
        """
        if self._bus is None:
            return None
        link = self._bus.find_link(from_agent, to_agent)
        if link is None:
            return None
        return MeshLinkPolicy(
            permissions=list(link.permissions),
            visible_memory_scopes=list(link.visible_memory_scopes),
            max_context_messages=int(link.max_context_messages),
        )

    def _resolve_policy(
        self, from_agent: str, to_agent: str, policy: MeshLinkPolicy | None
    ) -> MeshLinkPolicy | None:
        """显式传入的 policy 优先 (测试/特殊场景); 否则按 Link 解析。"""
        return policy if policy is not None else self.policy_for(from_agent, to_agent)

    async def notify(
        self, from_agent: str, to_agent: str, content: str, policy: MeshLinkPolicy | None = None
    ) -> bool:
        """单向通知 (不等待响应)。

        M2: ACL 通过后经 bus.send 投递 MeshMessageType.NOTIFY; 无 bus 时拒绝。
        P2: policy 省略时按 Link 解析 (policy_for)。
        """
        effective = self._resolve_policy(from_agent, to_agent, policy)
        if not self.is_permitted("notify", effective) or self._bus is None:
            self._audit("notify", from_agent, to_agent, allowed=False)
            return False
        self._audit("notify", from_agent, to_agent, allowed=True)
        return await self._send(from_agent, to_agent, content, MeshMessageType.NOTIFY) is not False

    async def handoff(
        self, from_agent: str, to_agent: str, summary: str, policy: MeshLinkPolicy | None = None
    ) -> bool:
        """移交会话所有权 (附会话摘要)。

        M2: 经 bus.send 投递 HANDOFF; summary 进 context.summary 让接收方读出交接上下文。
        会话归属的真实转移由调用方 (handoff_conversation 工具) 经 MessageRouter
        的 handoff 覆盖登记完成 —— broker 只负责把交接摘要投递给接手方。
        """
        effective = self._resolve_policy(from_agent, to_agent, policy)
        if not self.is_permitted("handoff", effective) or self._bus is None:
            self._audit("handoff", from_agent, to_agent, allowed=False)
            return False
        self._audit("handoff", from_agent, to_agent, allowed=True)
        sent = await self._send(
            from_agent, to_agent, summary, MeshMessageType.HANDOFF, extra_context={"summary": summary}
        )
        return sent is not False

    async def memory_query(
        self, from_agent: str, to_agent: str, query: str, policy: MeshLinkPolicy | None = None
    ) -> str | None:
        """跨 Agent 查询记忆 (受 visible_memory_scopes 裁剪), 返回响应文本。

        M2/P2: 经 bus.send 投递 MEMORY_QUERY; visible_memory_scopes 进
        context.filters.scopes 让接收方按 scope 裁剪。返回值:
        - str: 目标 Agent 的记忆检索结果 (空串 = 无命中)
        - None: ACL 拒绝 / 无 bus / 投递失败 (调用方据此报错)
        此前返回 bool 且丢弃 bus.send 的 response, 查询方永远拿不到结果。
        """
        effective = self._resolve_policy(from_agent, to_agent, policy)
        if not self.is_permitted("memory_query", effective) or self._bus is None:
            self._audit("memory_query", from_agent, to_agent, allowed=False)
            return None
        self._audit("memory_query", from_agent, to_agent, allowed=True)
        scopes = list(effective.visible_memory_scopes) if effective is not None else []
        response = await self._send(
            from_agent,
            to_agent,
            query,
            MeshMessageType.MEMORY_QUERY,
            extra_context={"filters": {"scopes": scopes}},
        )
        if response is False:
            return None
        return response.content if response is not None else ""

    async def _send(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        msg_type: MeshMessageType,
        *,
        extra_context: dict | None = None,
    ) -> Any:
        """构造 InterAgentMessage 并经 bus.send 投递; ACL 在 bus 内二次校验。

        返回: 响应 InterAgentMessage (同步返回的类型, 如 memory_query) /
        None (无响应, 如 notify) / False (ACL 拒绝或投递异常)。
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
            return await self._bus.send(message)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Mesh 动作投递失败",
                action=msg_type.value,
                from_agent=from_agent,
                to_agent=to_agent,
                error=str(exc),
            )
            return False

    @staticmethod
    def _audit(action: str, from_agent: str, to_agent: str, *, allowed: bool) -> None:
        """P2 动作审计埋点: 每次 A2A 动作 (含拒绝) 记结构化日志。

        经 trace 贯穿 (bind_log_context) 可与发起方的消息处理串联; 控制面
        data/audit.ndjson 只覆盖控制面写操作, A2A 动作审计以结构化日志为准
        (LOGGING.md), 后续可在此挂 audit_log 落盘。
        """
        if allowed:
            logger.info("Mesh 动作", action=action, from_agent=from_agent, to_agent=to_agent, allowed=True)
        else:
            logger.warning(
                "Mesh 动作被拒 (Link 未配置或未授予该权限)",
                action=action, from_agent=from_agent, to_agent=to_agent, allowed=False,
            )

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
