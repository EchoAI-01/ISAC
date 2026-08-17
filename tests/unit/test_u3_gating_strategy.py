"""U3 门控策略化专项测试 (配置 + i18n 词表 + LLM judge)。

验收覆盖 (DEVELOPMENT_PLAN §四 U3):
- 英文群聊场景门控 e2e 通过 (en_US 词表);
- 调整任何门控参数不改代码 (config 覆盖权重/阈值/词表/策略);
- zh_CN 默认配置下既有门控行为回归一致 (默认 profile = U3 前常量);
- GatingStrategy 四档 (off/keywords/llm-judge/hybrid);
- llm-judge 频率上限 + fail-safe 回落;
- 词汇表 drift test (config 与 locales 键一致性)。
"""

from __future__ import annotations

from typing import Any

import pytest

from isac.core.types import GatingContext
from isac.gateway.models import Session
from isac.gating.profile import GatingProfile
from isac.gating.strategy import (
    HybridStrategy,
    KeywordStrategy,
    LLMJudgeStrategy,
    OffStrategy,
    _JudgeRateLimiter,
    build_strategy,
)
from isac.gating.system import GatingSystem
from isac.locales import GATING_MARKER_KINDS, load_gating_markers


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


def _context(
    content: str,
    *,
    has_at: bool = False,
    has_mention: bool = False,
    is_private: bool = False,
) -> GatingContext:
    session = Session(session_id="s1", user_id="u1", agent_id="a1")
    return GatingContext(
        session=session,
        user_profile=None,
        current_message=_Msg(content),
        has_at=has_at,
        has_mention=has_mention,
        is_private=is_private,
    )


# ── 词汇表 drift test ────────────────────────────────────────


def test_locales_marker_kinds_consistent() -> None:
    """drift test: zh_CN 与 en_US 门控词表键集合一致 (均为规范三类)。"""
    from isac.locales import en_US, zh_CN

    assert set(zh_CN.GATING_MARKERS.keys()) == GATING_MARKER_KINDS
    assert set(en_US.GATING_MARKERS.keys()) == GATING_MARKER_KINDS
    for kind in GATING_MARKER_KINDS:
        assert zh_CN.GATING_MARKERS[kind], f"zh_CN {kind} 词表为空"
        assert en_US.GATING_MARKERS[kind], f"en_US {kind} 词表为空"


def test_load_gating_markers_fallback_and_kinds() -> None:
    markers = load_gating_markers("zh_CN")
    assert set(markers.keys()) == GATING_MARKER_KINDS
    # 未知语言回退默认语言
    assert load_gating_markers("xx_XX") == load_gating_markers("zh_CN")


# ── GatingProfile 配置化 ─────────────────────────────────────


def test_profile_default_matches_legacy_constants() -> None:
    """zh_CN 默认配置零行为变化: 默认 profile = U3 前框架常量。"""
    from isac.core import constants as c

    p = GatingProfile.from_config(None)
    assert p.strategy == "keywords"
    assert p.threshold == c.REPLY_NECESSITY_THRESHOLD
    assert p.base_at == c.GATING_BASE_SCORE_AT
    assert p.content_question == c.GATING_CONTENT_QUESTION
    assert p.content_short_reaction == c.GATING_CONTENT_SHORT_REACTION
    assert p.question_markers == tuple(load_gating_markers("zh_CN")["question"])


def test_profile_weights_overridable_from_config() -> None:
    """调整权重不改代码: config.weights 覆盖。"""
    p = GatingProfile.from_config({"weights": {"content_question": 99, "base_at": 55}})
    assert p.content_question == 99.0
    assert p.base_at == 55.0
    # 未覆盖项保持默认
    assert p.content_request == GatingProfile().content_request


def test_profile_locale_and_marker_override() -> None:
    """locale 切换词表; markers 覆盖优先于 locale。"""
    p_en = GatingProfile.from_config({"locale": "en_US"})
    assert "what" in p_en.question_markers
    assert "吗" not in p_en.question_markers

    p_override = GatingProfile.from_config(
        {"locale": "zh_CN", "markers": {"question": ["自定义疑问"]}}
    )
    assert p_override.question_markers == ("自定义疑问",)
    # 其余类仍取 locale 词表
    assert p_override.request_markers == tuple(load_gating_markers("zh_CN")["request"])


def test_profile_strategy_invalid_falls_back_keywords() -> None:
    assert GatingProfile.from_config({"strategy": "weird"}).strategy == "keywords"
    assert GatingProfile.from_config({"strategy": "hybrid"}).strategy == "hybrid"


# ── 策略四档 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_off_strategy_no_signals() -> None:
    s = OffStrategy()
    signals = await s.signals("今天天气怎么样", _context("今天天气怎么样"), mentioned=False)
    assert not signals.is_question and not signals.is_request and not signals.is_consult


@pytest.mark.asyncio
async def test_keyword_strategy_zh() -> None:
    p = GatingProfile.from_config({"locale": "zh_CN"})
    s = KeywordStrategy(p)
    ctx = _context("今天天气怎么样")
    signals = await s.signals("今天天气怎么样", ctx, mentioned=False)
    assert signals.is_question is True

    signals_req = await s.signals("请帮我查一下", _context("请帮我查一下"), mentioned=False)
    assert signals_req.is_request is True

    # 征询需提及
    ctx_mention = _context("你觉得怎么样", has_mention=True)
    signals_consult = await s.signals("你觉得怎么样", ctx_mention, mentioned=True)
    assert signals_consult.is_consult is True
    signals_no_mention = await s.signals("你觉得怎么样", _context("你觉得怎么样"), mentioned=False)
    assert signals_no_mention.is_consult is False


@pytest.mark.asyncio
async def test_keyword_strategy_en_case_insensitive() -> None:
    """en_US 词表大小写不敏感匹配。"""
    p = GatingProfile.from_config({"locale": "en_US"})
    s = KeywordStrategy(p)
    signals = await s.signals("WHAT is the Weather?", _context("WHAT is the Weather?"), mentioned=False)
    assert signals.is_question is True


@pytest.mark.asyncio
async def test_llm_judge_approved_and_fallback() -> None:
    p = GatingProfile.from_config({"strategy": "llm-judge"})

    async def judge_yes(content: str, context: Any) -> bool:
        return True

    s = LLMJudgeStrategy(p, judge_yes)
    signals = await s.signals("随便聊聊", _context("随便聊聊"), mentioned=False)
    assert signals.is_question is True and signals.judged_by_llm is True

    # judge 异常 → fail-safe 回落 keywords (无问询信号)
    async def judge_boom(content: str, context: Any) -> bool:
        raise RuntimeError("model down")

    s_boom = LLMJudgeStrategy(p, judge_boom)
    signals2 = await s_boom.signals("随便聊聊", _context("随便聊聊"), mentioned=False)
    assert signals2.judged_by_llm is False
    assert not signals2.is_question

    # judge 缺失 → 回落 keywords
    s_none = LLMJudgeStrategy(p, None)
    signals3 = await s_none.signals("今天天气怎么样", _context("今天天气怎么样"), mentioned=False)
    assert signals3.is_question is True and signals3.judged_by_llm is False


@pytest.mark.asyncio
async def test_llm_judge_rate_limit_falls_back() -> None:
    """频率上限: 超限后回落 keywords 不再调用 judge。"""
    p = GatingProfile.from_config({"strategy": "llm-judge", "llm_judge_max_per_minute": 1})
    calls: list[str] = []

    async def judge(content: str, context: Any) -> bool:
        calls.append(content)
        return True

    s = LLMJudgeStrategy(p, judge)
    await s.signals("msg1", _context("msg1"), mentioned=False)
    await s.signals("msg2", _context("msg2"), mentioned=False)
    assert len(calls) == 1  # 第二次超限回落


def test_rate_limiter_window() -> None:
    limiter = _JudgeRateLimiter(2)
    assert limiter.allow() is True
    assert limiter.allow() is True
    assert limiter.allow() is False


@pytest.mark.asyncio
async def test_hybrid_strategy_escalates_only_without_keyword_signal() -> None:
    p = GatingProfile.from_config({"strategy": "hybrid", "locale": "zh_CN"})
    judge_calls: list[str] = []

    async def judge(content: str, context: Any) -> bool:
        judge_calls.append(content)
        return True

    s = HybridStrategy(p, judge)
    # 含关键词 → keywords 直接判定, 不调 judge
    signals = await s.signals("今天天气怎么样", _context("今天天气怎么样"), mentioned=False)
    assert signals.is_question is True and judge_calls == []
    # 无关键词 → 升级 judge
    signals2 = await s.signals("hmm 有意思", _context("hmm 有意思"), mentioned=False)
    assert signals2.judged_by_llm is True and judge_calls == ["hmm 有意思"]


def test_build_strategy_factory() -> None:
    assert isinstance(build_strategy(GatingProfile.from_config({"strategy": "off"})), OffStrategy)
    assert isinstance(build_strategy(GatingProfile.from_config({})), KeywordStrategy)
    assert isinstance(
        build_strategy(GatingProfile.from_config({"strategy": "llm-judge"})), LLMJudgeStrategy
    )
    assert isinstance(build_strategy(GatingProfile.from_config({"strategy": "hybrid"})), HybridStrategy)


# ── 英文群聊场景门控 e2e ─────────────────────────────────────


@pytest.mark.asyncio
async def test_english_group_gating_e2e() -> None:
    """验收: 英文群聊配置 en_US 词表后, 英文问句评分达阈值触发; zh_CN 词表则漏判。

    注: 用例刻意不带 "?" —— ASCII 问号同时存在于 zh_CN/en_US 词表, 带问号会
    双语词表都命中, 无法区分 locale 词表差异。
    """
    # en_US: 英文疑问词命中 question 标记 (+15 >= 阈值 15) → TRIGGER
    gating_en = GatingSystem(config={"locale": "en_US", "reply_necessity_threshold": 15})
    decision_en = await gating_en.evaluate([], _context("what is the plan"))
    assert decision_en.kind.value == "trigger"

    # 同一消息在 zh_CN 词表下无 question 信号 (中文词表不含英文疑问词) → 分数 0 → WAIT
    gating_zh = GatingSystem(config={"locale": "zh_CN", "reply_necessity_threshold": 15})
    decision_zh = await gating_zh.evaluate([], _context("what is the plan"))
    assert decision_zh.kind.value == "wait"


@pytest.mark.asyncio
async def test_threshold_config_change_no_code() -> None:
    """调整阈值不改代码: 同一消息按配置阈值改变触发结果。"""
    msg = "帮我查一下天气"  # request +20
    low = GatingSystem(config={"reply_necessity_threshold": 10})
    high = GatingSystem(config={"reply_necessity_threshold": 50})
    assert (await low.evaluate([], _context(msg))).kind.value == "trigger"
    assert (await high.evaluate([], _context(msg))).kind.value == "wait"


def test_gating_config_merge_global_agent() -> None:
    """全局 config.gating 与 Agent 级合并: Agent 键优先, 嵌套浅合并。"""
    from isac.runtime.assembly import _merged_gating_config

    merged = _merged_gating_config(
        {"gating": {"strategy": "hybrid", "weights": {"content_question": 10}}},
        {"weights": {"content_question": 30}, "locale": "en_US"},
    )
    assert merged["strategy"] == "hybrid"  # 全局保留
    assert merged["locale"] == "en_US"  # Agent 新增
    assert merged["weights"]["content_question"] == 30  # Agent 覆盖嵌套键
