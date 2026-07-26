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
        reason = runtime.interrupt_state.reason
        hint = (
            "【内部参考】上一轮你正在思考时被新消息打断"
            + (f"（原因: {reason}）" if reason else "")
            + f", 共被打断 {count} 次。请基于最新消息重新组织回复, "
            "不要继续被打断前的旧思路。这是内部参考, 不要向用户逐字复述。"
        )
        # 注入后清空状态, 避免下一轮重复注入
        runtime.clear_interrupt()
        return hint
