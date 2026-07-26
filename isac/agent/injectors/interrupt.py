"""interrupt 注入器: 上一轮被打断的内部参考提示 (L4)。

注入 "上一轮被新消息打断" 内部参考到 System Prompt, 让 Agent 知道刚被新消息
打断, 而非逐字回应用户。注入后清空 interrupt_state, 避免下一轮重复注入。

仅当 runtime_provider 注入且对应 session 的 interrupt_state 非空时生效;
否则返回空串 (零行为变化)。

CR2-Fix-8: 构造参数从单一 ``runtime: ConversationRuntime`` 改为
``runtime_provider: Callable[[str], ConversationRuntime | None]`` —— 单一
runtime 实例无法正确服务多个 session (prompt_builder 是每个 Agent 一个实例,
服务该 Agent 的所有 session, 而 ConversationRuntime 是按 (agent_id, session_id)
创建的)。回调按 context.session.session_id 动态查询, assembly.py 用闭包固定
agent_id 传入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.core.injector import PromptInjector
from isac.core.types import InjectionContext

if TYPE_CHECKING:
    from collections.abc import Callable

    from isac.runtime.conversation import ConversationRuntime

# CR2-Fix-9: reason 长度上限。若未来接入真实消息内容作为打断原因, 无长度限制
# 会被用作把大段任意文本塞进 system prompt 的载体。
_MAX_REASON_LENGTH = 100


def _sanitize_reason(reason: str) -> str:
    """清理打断原因: 剔除换行/控制字符 (防伪装成新指令), 截断到合理长度。

    str.isprintable() 对空格返回 True, 对 \\n/\\r/\\t 等控制字符返回 False,
    足够同时保留正常文本可读性与过滤危险字符。
    """
    stripped = "".join(ch for ch in reason if ch.isprintable())
    if len(stripped) > _MAX_REASON_LENGTH:
        return stripped[:_MAX_REASON_LENGTH] + "…"
    return stripped


class InterruptInjector(PromptInjector):
    """注入"上一轮被打断"内部参考 (L4)。"""

    def __init__(
        self, *, runtime_provider: Callable[[str], ConversationRuntime | None] | None = None
    ) -> None:
        self._runtime_provider = runtime_provider

    @property
    def key(self) -> str:
        return "interrupt_hint"

    @property
    def priority(self) -> int:
        return 30  # 中等优先, 在 base_identity/tools 之后注入

    @property
    def tokens_estimate(self) -> int:
        return 80

    async def build(self, context: InjectionContext) -> str:
        if self._runtime_provider is None:
            return ""
        session_id = getattr(context.session, "session_id", "") if context.session else ""
        runtime = self._runtime_provider(session_id)
        if runtime is None or runtime.interrupt_state is None:
            return ""
        count = runtime.interrupt_state.interrupt_count
        reason = _sanitize_reason(runtime.interrupt_state.reason)
        hint = (
            "【内部参考】上一轮你正在思考时被新消息打断"
            + (f"（原因: {reason}）" if reason else "")
            + f", 共被打断 {count} 次。请基于最新消息重新组织回复, "
            "不要继续被打断前的旧思路。这是内部参考, 不要向用户逐字复述。"
        )
        # 注入后清空状态, 避免下一轮重复注入
        runtime.clear_interrupt()
        return hint
