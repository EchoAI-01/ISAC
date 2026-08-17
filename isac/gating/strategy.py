"""U3 GatingStrategy: 门控内容判定策略 (可插拔四档)。

四档 (``config.gating.strategy``):
- ``off``: 内容判定恒无信号 (群聊普通消息仅凭 @/提及/压力分触发)。
- ``keywords`` (默认): 关键词表匹配 (词表来自 locales, U3 前行为)。
- ``llm-judge``: 用小模型判群聊发言相关性; 频率上限防护, 失败/超限 fail-safe
  回落 keywords。
- ``hybrid``: keywords 先行, 无任何问询信号时升级 llm-judge 复判。

策略只产出**内容信号** (is_question/is_request/is_consult), 分数换算仍归
ReplyNecessityJudge (权重在 GatingProfile) —— 单一调用点, 策略可换而评分模型不变。

llm-judge 成本说明见 ARCHITECTURE.md 3.7 (频率上限 + 最便宜 fallback 档)。
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from isac.gating.profile import (
    STRATEGY_HYBRID,
    STRATEGY_LLM_JUDGE,
    STRATEGY_OFF,
    GatingProfile,
)
from isac.utils.logger import get_logger

logger = get_logger(__name__)

# judge_fn 签名: (content, context) -> 相关性 bool | None (None = 无法判定, 回落)。
JudgeFn = Callable[[str, Any], Awaitable[bool | None]]


@dataclass
class ContentSignals:
    """内容判定信号 (策略产出, 评分器消费)。"""

    is_question: bool = False
    is_request: bool = False
    is_consult: bool = False
    judged_by_llm: bool = False  # True = 信号来自 llm-judge (审计/调试)


def _contains_any(content: str, markers: tuple[str, ...]) -> bool:
    """大小写不敏感的子串匹配 (中文词表不受 lower 影响, 英文词表受益)。"""
    lowered = content.lower()
    return any(marker.lower() in lowered for marker in markers if marker)


class GatingStrategy:
    """内容判定策略基类。"""

    async def signals(self, content: str, context: Any, mentioned: bool) -> ContentSignals:
        raise NotImplementedError


class OffStrategy(GatingStrategy):
    """off 档: 恒无内容信号。"""

    async def signals(self, content: str, context: Any, mentioned: bool) -> ContentSignals:
        return ContentSignals()


class KeywordStrategy(GatingStrategy):
    """keywords 档 (默认): 词表匹配, 与 U3 前 reply_necessity 内容判定同语义。"""

    def __init__(self, profile: GatingProfile) -> None:
        self._profile = profile

    async def signals(self, content: str, context: Any, mentioned: bool) -> ContentSignals:
        p = self._profile
        return ContentSignals(
            is_question=_contains_any(content, p.question_markers),
            is_request=_contains_any(content, p.request_markers),
            # 征询需 @ 或提及 (与 U3 前语义一致)
            is_consult=mentioned and _contains_any(content, p.consult_markers),
        )


class _JudgeRateLimiter:
    """滑动窗口频率上限 (每分钟最多 N 次 judge 调用, 成本防护)。"""

    def __init__(self, max_per_minute: int) -> None:
        self._max = max(0, int(max_per_minute))
        self._calls: deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        while self._calls and now - self._calls[0] > 60.0:
            self._calls.popleft()
        if len(self._calls) >= self._max:
            return False
        self._calls.append(now)
        return True


class LLMJudgeStrategy(GatingStrategy):
    """llm-judge 档: 小模型判相关性。

    fail-safe: judge_fn 缺失/异常/返回 None/超频率上限 → 回落 keywords 档信号
    (宁可保守也不因判定器故障改变门控可用性)。
    """

    def __init__(self, profile: GatingProfile, judge_fn: JudgeFn | None = None) -> None:
        self._profile = profile
        self._judge_fn = judge_fn
        self._fallback = KeywordStrategy(profile)
        self._limiter = _JudgeRateLimiter(profile.llm_judge_max_per_minute)

    async def signals(self, content: str, context: Any, mentioned: bool) -> ContentSignals:
        if self._judge_fn is None or not content.strip():
            return await self._fallback.signals(content, context, mentioned)
        if not self._limiter.allow():
            logger.debug("llm-judge 频率超限, 回落 keywords")
            return await self._fallback.signals(content, context, mentioned)
        try:
            relevant = await self._judge_fn(content, context)
        except Exception as exc:  # noqa: BLE001 判定器故障 fail-safe 回落
            logger.warning("llm-judge 调用失败, 回落 keywords", error=str(exc))
            return await self._fallback.signals(content, context, mentioned)
        if relevant is None:
            return await self._fallback.signals(content, context, mentioned)
        # 判定相关 → 以 question 信号计入内容分 (保留评分模型不变)
        return ContentSignals(is_question=bool(relevant), judged_by_llm=True)


class HybridStrategy(GatingStrategy):
    """hybrid 档: keywords 先行, 无任何问询信号时升级 llm-judge 复判。"""

    def __init__(self, profile: GatingProfile, judge_fn: JudgeFn | None = None) -> None:
        self._keywords = KeywordStrategy(profile)
        self._judge = LLMJudgeStrategy(profile, judge_fn)

    async def signals(self, content: str, context: Any, mentioned: bool) -> ContentSignals:
        kw = await self._keywords.signals(content, context, mentioned)
        if kw.is_question or kw.is_request or kw.is_consult:
            return kw
        return await self._judge.signals(content, context, mentioned)


def build_strategy(profile: GatingProfile, judge_fn: JudgeFn | None = None) -> GatingStrategy:
    """按 profile.strategy 构造策略实例 (未知档位 from_config 已归一为 keywords)。"""
    if profile.strategy == STRATEGY_OFF:
        return OffStrategy()
    if profile.strategy == STRATEGY_LLM_JUDGE:
        return LLMJudgeStrategy(profile, judge_fn)
    if profile.strategy == STRATEGY_HYBRID:
        return HybridStrategy(profile, judge_fn)
    return KeywordStrategy(profile)  # STRATEGY_KEYWORDS (默认)
