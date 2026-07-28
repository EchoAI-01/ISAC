"""wait 工具: 暂缓回复，等待更多消息。

L2: conversation.enabled=True 时向本会话 ConversationRuntime 注册 WaitState
(runtime.enter_wait), 由 timeout / message / proactive 结束并回填 wait 工具结果
(说明实际等待时长); enabled=False 时返回意图字符串 (零行为变化)。
"""

from __future__ import annotations

import asyncio
import time
import uuid

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult
from isac.runtime.conversation import WaitEndReason, WaitState


class WaitTool(Tool):
    @property
    def name(self) -> str:
        return "wait"

    @property
    def description(self) -> str:
        return "暂时不回复，等待对方继续说"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"seconds": {"type": "integer", "description": "等待秒数", "default": 5}},
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """L2: enabled=True 时注册 WaitState 并 await, 唤醒后回填实际等待时长 + 原因。

        enabled=False (默认) 时返回意图字符串, 保持现有行为 (零行为变化)。
        """
        # CR2-Fix-2: 至少 1 秒下限, 不能是 0/负数——requested_seconds=None 不会创建
        # 超时定时器, 若 MESSAGE/PROACTIVE 唤醒路径也未被触发就会永久挂起。
        seconds = max(1, int(context.args.get("seconds", 5) or 5))
        session_id = getattr(context.agent_context.session, "session_id", "")
        agent_id = str(context.services.get("agent_id", "") or "")
        registry = context.services.get("conversation_registry")
        enabled = bool(context.services.get("conversation_enabled", False))
        if not enabled or registry is None:
            return ToolResult(content=f"已记录等待意图：等待 {seconds} 秒或等待对方继续说。session_id={session_id}")
        # L2: 注册 WaitState, await future 唤醒, 回填实际等待 + 原因
        runtime = registry.get(agent_id, session_id)
        tool_call_id = context.services.get("tool_call_id") or f"wait_{uuid.uuid4().hex}"
        wait = WaitState(
            tool_call_id=tool_call_id,
            started_at=time.time(),
            requested_seconds=float(seconds),
            reason="wait_tool",
        )
        await runtime.enter_wait(wait)
        # R18: hard timeout 防止 await_wait 永久挂起。协程被取消 (shutdown/lock 释放/
        # subagent 超时) 时 future 永不 resolve; wrap asyncio.wait_for 兜底。
        try:
            resolved = await asyncio.wait_for(
                runtime.await_wait(tool_call_id),
                timeout=seconds + 1,
            )
        except TimeoutError:
            return ToolResult(
                content=(
                    f"等待超时 (hard cap {seconds + 1}s)，"
                    f"唤醒原因：等待超时。session_id={session_id}"
                )
            )
        finally:
            # Fix-33: 硬超时兜底触发 (或本协程被外部取消) 时, 正常的三条唤醒路径
            # (message/timeout/proactive) 都没机会跑完 resolve_wait, runtime.state
            # 会永久停在 WAITING、pending_wait 也不会被清空。这里补做同样的清理;
            # 正常路径下 resolve_wait 早已清空 pending_wait, 这个 finally 是 no-op
            # (只在 pending_wait 仍是我们自己创建的这个 wait 时才清理, 避免误清理
            # 期间可能已合法开始的下一个 wait)。getattr 兜底: registry.get() 返回值
            # 只按 enter_wait/await_wait 的最小协议 duck-type, 不强制要求
            # pending_wait/resolve_wait (测试里允许传入更精简的 stub)。
            if getattr(runtime, "pending_wait", None) is wait:
                runtime.resolve_wait(WaitEndReason.TIMEOUT)
        end_reason = resolved.end_reason or WaitEndReason.TIMEOUT
        return ToolResult(
            content=(
                f"已等待 {resolved.actual_seconds:.1f} 秒，"
                f"唤醒原因：{_reason_label(end_reason)}。session_id={session_id}"
            )
        )


def _reason_label(reason: WaitEndReason) -> str:
    """把枚举值转成中文标签, 便于 LLM 理解 wait 工具结果。"""
    if reason is WaitEndReason.MESSAGE:
        return "收到新消息"
    if reason is WaitEndReason.TIMEOUT:
        return "等待超时"
    if reason is WaitEndReason.PROACTIVE:
        return "被主动任务唤醒"
    return reason.value
