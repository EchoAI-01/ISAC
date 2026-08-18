"""handoff_conversation 工具 (M2, ROUTING_AND_AGENT_MESH.md §5.2)。

把当前会话移交给另一个 Agent (附会话摘要)。默认 restricted; M2 已接入
MeshActionBroker.handoff。
"""

from __future__ import annotations

from typing import Any

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult
from isac.runtime.mesh.models import MeshLinkPolicy
from isac.utils.logger import get_logger

logger = get_logger(__name__)


def _transfer_ownership(
    router: Any, session: Any, agent_id: str, target: str, summary: str
) -> ToolResult:
    """Fix-117 (从 execute 抽出, 降圈复杂度): 在 MessageRouter 登记归属转移。

    router/session 缺失时降级为"仅摘要已送达"; target==agent_id 为交还 (撤销覆盖)。
    """
    if router is None or session is None:
        return ToolResult(content=f"已通知 {target} 接手 (摘要已送达), 摘要: {summary[:50]}")
    platform = getattr(session, "platform", "")
    group_id = getattr(session, "group_id", None)
    user_id = getattr(session, "user_id", "")
    if target == agent_id:
        # 移交给自己 = 交还归属 (撤销此前的移交覆盖)
        router.clear_handoff(platform, group_id, user_id)
        return ToolResult(content=f"已交还会话归属 (撤销移交), 摘要: {summary[:50]}")
    router.set_handoff(platform, group_id, user_id, target)
    return ToolResult(content=f"已移交会话给 {target} (后续消息由其接手), 摘要: {summary[:50]}")


class HandoffConversationTool(Tool):
    @property
    def name(self) -> str:
        return "handoff_conversation"

    @property
    def description(self) -> str:
        return "把当前会话移交给另一个 Agent 接手 (仅限已互联的 Agent)"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "target_agent": {"type": "string", "description": "接手的 Agent ID"},
                "summary": {"type": "string", "description": "移交时附带的会话摘要"},
            },
            "required": ["target_agent", "summary"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """M2/P2: 摘要投递 + **会话归属真实转移**。

        此前只经 bus 发一条 HANDOFF 消息, Router 侧无任何变化 —— 后续消息仍路由
        给移交方, "移交"只是聊天。P2 补上归属转移: 摘要投递成功后在 MessageRouter
        登记 handoff 覆盖 (platform + 群/私聊主体 → 接手 Agent), 该会话后续消息
        直接路由给接手方 (优先级最高; 内存态, 重启回落常规规则)。

        Fix-117: ① **gate 顺序** —— 此前先投递摘要再预约 SessionWriteGate, 租约被
        仲裁拒绝时摘要已白发 (半程移交: 对方收到交接摘要但归属没转, 且发起方收到
        "移交暂缓"误以为没发生)。现在预约前置: 拿不到租约立即返回, 不做任何投递。
        ② **失败不 commit** —— 此前 finally 无条件 commit, 投递/转移失败也把租约标
        记为"写入成功"。改为: 成功路径显式 commit, 其余 (失败返回/异常) 一律 cancel。
        """
        broker = context.services.get("mesh_action_broker")
        if broker is None:
            return ToolResult(content="handoff_conversation 未接入 mesh_action_broker", is_error=True)
        policy: MeshLinkPolicy | None = context.services.get("mesh_link_policy")
        target = str(context.args.get("target_agent", ""))
        summary = str(context.args.get("summary", ""))
        agent_id = str(context.services.get("agent_id", ""))
        router = context.services.get("router")
        # Fix-70: 登记前存活性检查 —— 目标不在 agents_provider (生产即非 running)
        # 时拒绝移交: 否则摘要白发, 且会话被一个无人接手的 handoff 覆盖劫持到
        # TTL 到期。交还 (target==自己) 不受此限制, 撤销路径必须始终可用。
        if router is not None and target and target != agent_id and not router.is_agent_routable(target):
            return ToolResult(
                content=f"移交失败: 目标 Agent {target} 当前未运行, 无法接手会话。", is_error=True
            )
        # Fix-117①: 归属转移是会话流写入, 先预约后写入 (fail-closed) —— 预约必须
        # 在任何投递副作用之前, 被仲裁拒绝时不产生半程移交。
        session = context.agent_context.session
        gate = context.services.get("session_write_gate")
        reservation = None
        if gate is not None:
            session_key = getattr(session, "session_id", "") or f"handoff:{agent_id}"
            reservation = gate.reserve(session_key, "handoff")
            if reservation is None:
                return ToolResult(
                    content="移交暂缓: 该会话有在途写入 (SessionWriteGate 仲裁), 请稍后重试。",
                    is_error=True,
                )
        try:
            ok = await broker.handoff(agent_id, target, summary, policy)
            if not ok:
                return ToolResult(
                    content=f"移交 {target} 失败 (Link 未配置或未授予 handoff 权限)", is_error=True
                )
            # P2: 会话归属转移 —— router 经 services 注入 (无 router 时降级为仅投递摘要)。
            # MVP-Fix: 移交带 TTL (router.DEFAULT_HANDOFF_TTL_SECONDS), 到期归属自动
            # 回落常规路由; 接手方把会话移交回原归属者即可提前撤销。
            result = _transfer_ownership(router, session, agent_id, target, summary)
            # Fix-117②: 仅成功路径 commit; 置空后 finally 的 cancel 对本租约无操作。
            if gate is not None and reservation is not None:
                if not gate.commit(reservation):
                    logger.warning(
                        "handoff 租约提交未生效 (可能已过期), 归属转移已完成",
                        target=target, session_id=getattr(session, "session_id", ""),
                    )
                reservation = None
            return result
        finally:
            if gate is not None and reservation is not None:
                gate.cancel(reservation)
