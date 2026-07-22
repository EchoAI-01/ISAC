"""BehaviorLearner: 从回复中学习行为模式 (ARCHITECTURE.md 3.5 Hooks 表)。

注册 FINAL_RESPONSE hook: 分析本轮回复, 提取行为特征 (回复长度 / emoji 使用 /
话题偏好) 写入 UserProfile.behavior_patterns。

行为模式只保留最近 N 条, 避免无限增长。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.agent.hooks import AgentHooks
from isac.core.events import AgentHookPoint
from isac.core.types import AgentContext, LLMResponse
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.gateway.models import UserProfile

logger = get_logger(__name__)

EMOJI_CHARS = "😀😁😂🤣😊😍🥰😘😗☺️🙂🤐😭😴🤔🤯😱🎉👍👎👏🙏🔥💯"
MAX_PATTERNS = 20


class BehaviorLearner:
    """行为模式学习器 (按 Agent 独立实例)。"""

    def __init__(self, max_patterns: int = MAX_PATTERNS) -> None:
        self.max_patterns = max(1, max_patterns)

    def register_hooks(self, hooks: AgentHooks) -> None:
        """注册到 AgentHooks (组装时调用)。"""
        hooks.register(AgentHookPoint.FINAL_RESPONSE, self._on_final_response)

    async def _on_final_response(self, response: LLMResponse, context: AgentContext) -> None:
        """从 FINAL_RESPONSE 提取行为特征, 写入 UserProfile.behavior_patterns。"""
        profile = context.user_profile
        if profile is None:
            return

        content = response.content or ""
        pattern = self._extract_pattern(content)
        try:
            self._append_pattern(profile, pattern)
        except Exception as exc:  # 防御: 学习失败不应影响主链路
            logger.warning("行为模式学习失败", user_id=profile.user_id, error=str(exc))

    def _extract_pattern(self, content: str) -> dict:
        """从回复文本提取行为特征。"""
        length = len(content)
        emoji_count = sum(1 for ch in content if ch in EMOJI_CHARS)
        # 简单话题识别: 中文前 20 字符, 截断
        topic_hint = content.strip()[:20]
        return {
            "length": length,
            "emoji_count": emoji_count,
            "length_bucket": self._bucket(length),
            "topic_hint": topic_hint,
        }

    @staticmethod
    def _bucket(length: int) -> str:
        if length <= 5:
            return "short"
        if length <= 50:
            return "medium"
        if length <= 200:
            return "long"
        return "very_long"

    def _append_pattern(self, profile: UserProfile, pattern: dict) -> None:
        """profile.behavior_patterns 追加, 超过上限丢弃最旧。"""
        patterns = profile.behavior_patterns
        patterns.append(pattern)
        overflow = len(patterns) - self.max_patterns
        if overflow > 0:
            del patterns[:overflow]
