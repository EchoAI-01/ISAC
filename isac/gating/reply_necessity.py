"""回复必要性评分 (ARCHITECTURE.md 3.7)。

评分模型:
  基础分: has_at(100) | has_mention(80) | private(40) | focus(40) | 普通(0)  取适用项最大值
  + 内容分:
      - 问题: 含问号/疑问词，+15
      - 请求: 含 "请"/"帮我"/"能不能" 等委托词，+20
      - 征询: 被 @ 或提及 且含 "你觉得"/"怎么看" 等征求意见句，+20
      - 长文本: > 120 字 +5，> 240 字 +10
      - 短反应: <= 5 字且无上述问询信号（如 "哈哈"、"嗯"），-25
  + 压力分: pending 消息积压 (每条 +15，封顶 100)
  - 存在感惩罚: 近窗口本 Agent 发言占比 (0~-25)
  × 频率系数 (0.5~1.0，effective_frequency)
  阈值: REPLY_NECESSITY_THRESHOLD (80)，由 GatingSystem 比较。

注: has_at / (private + mention) / focus 已在 GatingSystem.evaluate 中前置强制触发，
score() 主要服务群聊「提及但未 @」与普通消息路径；基础分逻辑保留完整以便直接测试。
"""

from __future__ import annotations

from isac.channel.model import ISACMessage
from isac.core.constants import (
    GATING_BASE_SCORE_AT,
    GATING_BASE_SCORE_FOCUS,
    GATING_BASE_SCORE_MENTION,
    GATING_BASE_SCORE_PRIVATE,
    GATING_CONSULT_MARKERS,
    GATING_CONTENT_CONSULT,
    GATING_CONTENT_LONG_TEXT,
    GATING_CONTENT_LONG_TEXT_EXTRA,
    GATING_CONTENT_QUESTION,
    GATING_CONTENT_REQUEST,
    GATING_CONTENT_SHORT_REACTION,
    GATING_FREQUENCY_MAX,
    GATING_FREQUENCY_MIN,
    GATING_LONG_TEXT_THRESHOLD,
    GATING_LONG_TEXT_THRESHOLD_EXTRA,
    GATING_PRESENCE_PENALTY_MAX,
    GATING_PRESSURE_CAP,
    GATING_PRESSURE_PER_PENDING,
    GATING_QUESTION_MARKERS,
    GATING_REQUEST_MARKERS,
    GATING_SHORT_REACTION_MAX_LEN,
    REPLY_NECESSITY_THRESHOLD,
)
from isac.core.types import GatingContext


class ReplyNecessityJudge:
    """回复必要性评分器 (ARCHITECTURE.md 3.7)。"""

    def __init__(self, threshold: int = REPLY_NECESSITY_THRESHOLD):
        self.threshold = threshold

    async def score(self, pending: list[ISACMessage], context: GatingContext) -> float:
        """计算回复必要性得分。

        Args:
            pending: 当前积压的消息列表（含当前消息）。
            context: 门控上下文（基础信号 + 频率/存在感状态）。

        Returns:
            回复必要性得分（>= 0）；GatingSystem 与 threshold 比较决定是否触发。
        """
        content = (context.current_message.content or "").strip()

        base = self._base_score(context)
        content_score = self._content_score(content, context)
        pressure = min(context.pending_count * GATING_PRESSURE_PER_PENDING, GATING_PRESSURE_CAP)
        presence_penalty = self._presence_penalty(context)
        frequency = self._clamp_frequency(context.effective_frequency)

        raw = base + content_score + pressure - presence_penalty
        return max(0.0, raw * frequency)

    @staticmethod
    def _base_score(context: GatingContext) -> float:
        """基础分：取适用信号中的最高档。"""
        if context.has_at:
            return float(GATING_BASE_SCORE_AT)
        if context.has_mention:
            return float(GATING_BASE_SCORE_MENTION)
        if context.focus_active:
            return float(GATING_BASE_SCORE_FOCUS)
        if context.is_private:
            return float(GATING_BASE_SCORE_PRIVATE)
        return 0.0

    @staticmethod
    def _content_score(content: str, context: GatingContext) -> float:
        """内容分：问题/请求/征询/长文本加分，纯短反应扣分。"""
        if not content:
            return 0.0

        is_question = any(marker in content for marker in GATING_QUESTION_MARKERS)
        is_request = any(marker in content for marker in GATING_REQUEST_MARKERS)
        mentioned = context.has_at or context.has_mention
        is_consult = mentioned and any(marker in content for marker in GATING_CONSULT_MARKERS)

        score = 0.0
        if is_question:
            score += GATING_CONTENT_QUESTION
        if is_request:
            score += GATING_CONTENT_REQUEST
        if is_consult:
            score += GATING_CONTENT_CONSULT

        length = len(content)
        if length > GATING_LONG_TEXT_THRESHOLD_EXTRA:
            score += GATING_CONTENT_LONG_TEXT_EXTRA
        elif length > GATING_LONG_TEXT_THRESHOLD:
            score += GATING_CONTENT_LONG_TEXT

        # 短反应扣分：仅当没有任何问询信号时才算「无意义短回应」
        if not (is_question or is_request or is_consult) and length <= GATING_SHORT_REACTION_MAX_LEN:
            score += GATING_CONTENT_SHORT_REACTION

        return score

    @staticmethod
    def _presence_penalty(context: GatingContext) -> float:
        """存在感惩罚：近窗口本 Agent 发言占比越高，越抑制发言 (0~上限)。"""
        window = context.recent_window_messages
        if window <= 0:
            return 0.0
        ratio = min(context.recent_self_replies / window, 1.0)
        return GATING_PRESENCE_PENALTY_MAX * ratio

    @staticmethod
    def _clamp_frequency(frequency: float) -> float:
        """频率系数限制在 [下限, 上限]。"""
        return max(GATING_FREQUENCY_MIN, min(GATING_FREQUENCY_MAX, frequency))
