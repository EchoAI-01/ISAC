"""InterAgentBus: Agent 间通信总线 (ARCHITECTURE.md 3.3 / SPECIFICATION.md 2.10)。

默认不互通，必须显式配置 Link (ACL)。总线是天然审计点 (ADR-009)。

Link 持久化由外部注入可选的 persist_callback (main.py 把 data/links.jsonc 落盘
逻辑包装成回调); 未注入时退化为纯 in-memory (测试场景默认行为)。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from isac.core.exceptions import InterAgentLinkDeniedError
from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 投递回调: 由 AgentManager 注入 (agent_id, InterAgentMessage) -> 响应文本
DeliverFn = Callable[[str, "InterAgentMessage"], Awaitable[str | None]]
# 持久化回调: 由 main.py 注入, 把当前 links 快照写入 data/links.jsonc。
# 失败时回调内自行决定是抛异常还是仅记录日志 (CODE_REVIEW_REPORT.md #3/#20)。
PersistFn = Callable[[], None] | None


@dataclass
class InterAgentLink:
    """Agent 互联链路 (data/links.jsonc, ACL)"""

    from_agent: str
    to_agent: str
    direction: str = "both"  # "both" | "oneway"
    enabled: bool = True


@dataclass
class InterAgentMessage:
    """Agent 间消息"""

    from_agent: str
    to_agent: str
    type: str  # "request" | "response" | "notify" | "handoff"
    content: str
    context: dict = field(default_factory=dict)


class InterAgentBus:
    """Agent 间通信总线。"""

    def __init__(self, deliver: DeliverFn | None = None, persist: PersistFn = None):
        self._links: list[InterAgentLink] = []
        self._deliver = deliver
        self._persist = persist

    def set_deliver(self, deliver: DeliverFn) -> None:
        """注入投递回调 (由 main.py 接线)。"""
        self._deliver = deliver

    def set_persist(self, persist: PersistFn) -> None:
        """注入 Link 持久化回调 (由 main.py 接线)。"""
        self._persist = persist

    def _trigger_persist(self) -> None:
        """Link 变更后触发持久化; 回调缺失或抛异常都不影响 in-memory 状态。"""
        if self._persist is None:
            return
        try:
            self._persist()
        except Exception as exc:  # noqa: BLE001
            # 持久化失败已在 routes_routing.py 的 API 路径显式返回 500;
            # 走 bus 内部路径 (如启动时恢复后的 add_link) 时只记日志, 不让 in-memory
            # 操作被磁盘失败回滚 (CODE_REVIEW_REPORT.md #3/#20)。
            logger.warning("Link 持久化失败, in-memory 状态已变更", error=str(exc))

    # ── Link 管理 (控制面暴露) ─────────────────────────────

    def add_link(self, link: InterAgentLink) -> None:
        self._links.append(link)
        self._trigger_persist()
        logger.info("互联 Link 已添加", from_agent=link.from_agent, to_agent=link.to_agent)

    def remove_link(self, from_agent: str, to_agent: str) -> None:
        self._links = [
            link for link in self._links if not (link.from_agent == from_agent and link.to_agent == to_agent)
        ]
        self._trigger_persist()
        logger.info("互联 Link 已移除", from_agent=from_agent, to_agent=to_agent)

    def list_links(self) -> list[InterAgentLink]:
        return list(self._links)

    def can_talk(self, from_agent: str, to_agent: str) -> bool:
        """检查 ACL: 是否存在允许 from → to 的 Link。"""
        for link in self._links:
            if not link.enabled:
                continue
            if link.from_agent == from_agent and link.to_agent == to_agent:
                return True
            if link.direction == "both" and link.from_agent == to_agent and link.to_agent == from_agent:
                return True
        return False

    # ── 通信 ────────────────────────────────────────────────

    async def send(self, message: InterAgentMessage) -> InterAgentMessage | None:
        """发送互联消息: ACL 检查 → 投递 → 返回响应 (notify 返回 None)。

        TODO: handoff 类型的会话摘要交接; 超时控制。
        """
        if not self.can_talk(message.from_agent, message.to_agent):
            logger.warning(
                "互联被 ACL 拒绝",
                from_agent=message.from_agent,
                to_agent=message.to_agent,
            )
            raise InterAgentLinkDeniedError(f"Agent {message.from_agent} 无权与 {message.to_agent} 通信")

        logger.info(
            "互联消息",
            from_agent=message.from_agent,
            to_agent=message.to_agent,
            type=message.type,
        )
        if message.type == "notify" or self._deliver is None:
            return None

        response_content = await self._deliver(message.to_agent, message)
        return InterAgentMessage(
            from_agent=message.to_agent,
            to_agent=message.from_agent,
            type="response",
            content=response_content or "",
            context=message.context,
        )
