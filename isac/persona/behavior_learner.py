"""BehaviorLearner: 从回复中学习行为模式 (ARCHITECTURE.md 3.5 Hooks 表)。

注册 FINAL_RESPONSE hook: 分析本轮回复，更新 UserProfile.behavior_patterns。
"""

from __future__ import annotations

from isac.agent.hooks import AgentHooks
from isac.core.events import AgentHookPoint
from isac.core.types import AgentContext, LLMResponse
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class BehaviorLearner:
    """行为模式学习器 (按 Agent 独立实例)。

    TODO(Day 29): 从 FINAL_RESPONSE 提取行为特征 (回复长度/表情使用/话题偏好)，
    写入 UserProfile.behavior_patterns。
    """

    def register_hooks(self, hooks: AgentHooks) -> None:
        """注册到 AgentHooks (组装时调用)。"""
        hooks.register(AgentHookPoint.FINAL_RESPONSE, self._on_final_response)

    async def _on_final_response(self, response: LLMResponse, context: AgentContext) -> None:
        raise NotImplementedError("TODO(Day 29): 实现行为模式学习")
