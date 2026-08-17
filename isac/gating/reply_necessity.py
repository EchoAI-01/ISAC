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
from isac.core.types import GatingContext
from isac.gating.profile import GatingProfile
from isac.gating.strategy import GatingStrategy, build_strategy


class ReplyNecessityJudge:
    """回复必要性评分器 (ARCHITECTURE.md 3.7)。

    U3 门控策略化: 权重与词表收口到 GatingProfile (配置 + i18n), 内容判定经
    GatingStrategy 可插拔 (off/keywords/llm-judge/hybrid)。默认 profile =
    U3 前框架默认 (zh_CN keywords), 零行为变化。
    """

    def __init__(
        self,
        threshold: int | None = None,
        profile: GatingProfile | None = None,
        strategy: GatingStrategy | None = None,
    ):
        self.profile = profile or GatingProfile()
        # threshold 显式传入优先 (向后兼容旧构造签名), 否则用 profile 值。
        self.threshold = int(threshold) if threshold is not None else self.profile.threshold
        self.strategy = strategy or build_strategy(self.profile)

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
        content_score = await self._content_score(content, context)
        pressure = min(
            context.pending_count * self.profile.pressure_per_pending, self.profile.pressure_cap
        )
        presence_penalty = self._presence_penalty(context)
        frequency = self._clamp_frequency(context.effective_frequency)

        raw = base + content_score + pressure - presence_penalty
        return max(0.0, raw * frequency)

    def _base_score(self, context: GatingContext) -> float:
        """基础分：取适用信号中的最高档。"""
        p = self.profile
        if context.has_at:
            return float(p.base_at)
        if context.has_mention:
            return float(p.base_mention)
        if context.focus_active:
            return float(p.base_focus)
        if context.is_private:
            return float(p.base_private)
        return 0.0

    async def _content_score(self, content: str, context: GatingContext) -> float:
        """内容分：问题/请求/征询/长文本加分，纯短反应扣分。

        U3: 问询信号经 GatingStrategy 产出 (可插拔 off/keywords/llm-judge/hybrid)。
        """
        if not content:
            return 0.0
        p = self.profile

        mentioned = context.has_at or context.has_mention
        signals = await self.strategy.signals(content, context, mentioned)

        score = 0.0
        if signals.is_question:
            score += p.content_question
        if signals.is_request:
            score += p.content_request
        if signals.is_consult:
            score += p.content_consult

        length = len(content)
        if length > p.long_text_threshold_extra:
            score += p.content_long_text_extra
        elif length > p.long_text_threshold:
            score += p.content_long_text

        # 短反应扣分：仅当没有任何问询信号时才算「无意义短回应」
        has_inquiry = signals.is_question or signals.is_request or signals.is_consult
        if not has_inquiry and length <= p.short_reaction_max_len:
            score += p.content_short_reaction

        return score

    def _presence_penalty(self, context: GatingContext) -> float:
        """存在感惩罚：近窗口本 Agent 发言占比越高，越抑制发言 (0~上限)。"""
        window = context.recent_window_messages
        if window <= 0:
            return 0.0
        ratio = min(context.recent_self_replies / window, 1.0)
        return self.profile.presence_penalty_max * ratio

    def _clamp_frequency(self, frequency: float) -> float:
        """频率系数限制在 [下限, 上限]。"""
        return max(self.profile.frequency_min, min(self.profile.frequency_max, frequency))
