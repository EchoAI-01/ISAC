"""MoodTracker: 把 MoodEngine 接入生产 FINAL_RESPONSE 回路 (Q2 激活)。

情绪必须缓慢变化且自然衰减 (HUMANLIKE_RUNTIME.md 6.2), 不应因单条消息剧烈波动,
也不应臆造对用户情绪/话语的主观判断。因此本追踪器只用回合内已有的客观信号——
本轮工具调用数 (活跃度) ——作 arousal 的小幅扰动, valence 只交给 decay 回归中性;
每轮都会 decay, 使此前(如由其他子系统)累积的情绪随时间自然消退。

工具调用数取 ``context.tool_calls_this_turn`` (由 ISACAgentLoop 在每次工具调用
分支里累加), 不能取 ``response.tool_calls``——FINAL_RESPONSE 只在
``response.tool_calls`` 为空时触发 (那正是进入该分支而非工具执行分支的条件),
从 response 上读永远是 0, 会让扰动分支变成死代码。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.core.events import AgentHookPoint
from isac.core.types import AgentContext, LLMResponse

if TYPE_CHECKING:
    from isac.agent.hooks import AgentHooks
    from isac.persona.mood import MoodEngine

AROUSAL_STEP_PER_TOOL_CALL = 0.03  # 每次工具调用带来的 arousal 增量, 保持"缓慢变化"
MAX_TOOL_CALLS_COUNTED = 5  # 单轮工具调用数封顶, 避免工具风暴过度推高


class MoodTracker:
    """按 Agent 独立实例, 每轮成功完成的回复后更新 MoodEngine。"""

    def __init__(self, mood_engine: MoodEngine) -> None:
        self._mood_engine = mood_engine

    def register_hooks(self, hooks: AgentHooks) -> None:
        """注册到 AgentHooks (PersonaManager.register_hooks 调用)。"""
        hooks.register(AgentHookPoint.FINAL_RESPONSE, self._on_final_response)

    async def _on_final_response(self, response: LLMResponse, context: AgentContext) -> None:
        """FINAL_RESPONSE 后: 先自然衰减, 再按本轮工具调用数施加小幅 arousal 扰动。"""
        del response
        self._mood_engine.decay()
        tool_call_count = min(context.tool_calls_this_turn, MAX_TOOL_CALLS_COUNTED)
        if tool_call_count:
            self._mood_engine.update(arousal_delta=AROUSAL_STEP_PER_TOOL_CALL * tool_call_count)
