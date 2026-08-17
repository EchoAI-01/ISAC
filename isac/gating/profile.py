"""U3 GatingProfile: 门控参数画像 (配置 + i18n 词表)。

U3 之前评分权重与关键词表硬编码在 ``isac/core/constants.py`` (仅中文)。U3 把它们
统一收口到本画像: 数值权重从 ``config.gating.weights`` 读 (缺省回落到 constants),
question/request/consult 三类词表按 ``config.gating.locale`` 从 locales 双语包取
(zh_CN 为既有中文词表迁入, en_US 新增英文词表), 词表本身也可经
``config.gating.markers`` 覆盖。

**调整任何门控参数不改代码**: 全部字段都可经配置覆盖, 未配置时用框架默认值,
保证 zh_CN 默认配置下行为与 U3 前完全一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
from isac.locales import DEFAULT_LOCALE, load_gating_markers

# 策略档位 (GatingStrategy 可插拔四档)。
STRATEGY_OFF = "off"
STRATEGY_KEYWORDS = "keywords"
STRATEGY_LLM_JUDGE = "llm-judge"
STRATEGY_HYBRID = "hybrid"
VALID_STRATEGIES: frozenset[str] = frozenset(
    {STRATEGY_OFF, STRATEGY_KEYWORDS, STRATEGY_LLM_JUDGE, STRATEGY_HYBRID}
)


def _num(value: Any, default: float) -> float:
    """数值安全转换, 非法/缺失回落默认。"""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int) -> int:
    return int(_num(value, float(default)))


@dataclass
class GatingProfile:
    """门控参数画像 (权重 + 词表 + 策略档位)。"""

    strategy: str = STRATEGY_KEYWORDS
    locale: str = DEFAULT_LOCALE
    threshold: int = REPLY_NECESSITY_THRESHOLD

    # 基础分 (取适用信号最高档)
    base_at: float = GATING_BASE_SCORE_AT
    base_mention: float = GATING_BASE_SCORE_MENTION
    base_private: float = GATING_BASE_SCORE_PRIVATE
    base_focus: float = GATING_BASE_SCORE_FOCUS

    # 内容分
    content_question: float = GATING_CONTENT_QUESTION
    content_request: float = GATING_CONTENT_REQUEST
    content_consult: float = GATING_CONTENT_CONSULT
    content_long_text: float = GATING_CONTENT_LONG_TEXT
    content_long_text_extra: float = GATING_CONTENT_LONG_TEXT_EXTRA
    long_text_threshold: int = GATING_LONG_TEXT_THRESHOLD
    long_text_threshold_extra: int = GATING_LONG_TEXT_THRESHOLD_EXTRA
    content_short_reaction: float = GATING_CONTENT_SHORT_REACTION
    short_reaction_max_len: int = GATING_SHORT_REACTION_MAX_LEN

    # 压力分 / 存在感惩罚 / 频率系数
    pressure_per_pending: float = GATING_PRESSURE_PER_PENDING
    pressure_cap: float = GATING_PRESSURE_CAP
    presence_penalty_max: float = GATING_PRESENCE_PENALTY_MAX
    frequency_min: float = GATING_FREQUENCY_MIN
    frequency_max: float = GATING_FREQUENCY_MAX

    # 三类标记词表 (i18n); 数据类默认 = zh_CN 词表 (constants 同源), 直接构造
    # GatingProfile() 亦与 U3 前行为一致。from_config 按 locale 重新装载。
    question_markers: tuple[str, ...] = GATING_QUESTION_MARKERS
    request_markers: tuple[str, ...] = GATING_REQUEST_MARKERS
    consult_markers: tuple[str, ...] = GATING_CONSULT_MARKERS

    # llm-judge / hybrid 档参数
    llm_judge_max_per_minute: int = 10  # 频率上限 (成本防护)
    hybrid_escalate_band: float = 20.0  # hybrid: 分数落在 [threshold-band, threshold) 升级 LLM

    @classmethod
    def from_config(cls, config: dict[str, Any] | None = None) -> GatingProfile:
        """从 ``config.gating`` 构造画像。

        权重读 ``config["weights"]``, 词表按 ``config["locale"]`` 从 locales 取、
        可经 ``config["markers"]`` 覆盖; 策略档位读 ``config["strategy"]``
        (非法值回落 keywords)。全部缺省时 = U3 前的框架默认 (zh_CN 中文词表)。
        """
        config = config or {}
        locale = str(config.get("locale") or DEFAULT_LOCALE)
        markers = load_gating_markers(locale)
        marker_override = config.get("markers") or {}
        if isinstance(marker_override, dict):
            for kind in ("question", "request", "consult"):
                override = marker_override.get(kind)
                if isinstance(override, (list, tuple)) and override:
                    markers[kind] = tuple(str(m) for m in override)

        weights = config.get("weights") or {}
        if not isinstance(weights, dict):
            weights = {}

        strategy = str(config.get("strategy") or STRATEGY_KEYWORDS).strip().lower()
        if strategy not in VALID_STRATEGIES:
            strategy = STRATEGY_KEYWORDS

        return cls(
            strategy=strategy,
            locale=locale,
            threshold=_int(config.get("reply_necessity_threshold"), REPLY_NECESSITY_THRESHOLD),
            base_at=_num(weights.get("base_at"), GATING_BASE_SCORE_AT),
            base_mention=_num(weights.get("base_mention"), GATING_BASE_SCORE_MENTION),
            base_private=_num(weights.get("base_private"), GATING_BASE_SCORE_PRIVATE),
            base_focus=_num(weights.get("base_focus"), GATING_BASE_SCORE_FOCUS),
            content_question=_num(weights.get("content_question"), GATING_CONTENT_QUESTION),
            content_request=_num(weights.get("content_request"), GATING_CONTENT_REQUEST),
            content_consult=_num(weights.get("content_consult"), GATING_CONTENT_CONSULT),
            content_long_text=_num(weights.get("content_long_text"), GATING_CONTENT_LONG_TEXT),
            content_long_text_extra=_num(
                weights.get("content_long_text_extra"), GATING_CONTENT_LONG_TEXT_EXTRA
            ),
            long_text_threshold=_int(weights.get("long_text_threshold"), GATING_LONG_TEXT_THRESHOLD),
            long_text_threshold_extra=_int(
                weights.get("long_text_threshold_extra"), GATING_LONG_TEXT_THRESHOLD_EXTRA
            ),
            content_short_reaction=_num(
                weights.get("content_short_reaction"), GATING_CONTENT_SHORT_REACTION
            ),
            short_reaction_max_len=_int(
                weights.get("short_reaction_max_len"), GATING_SHORT_REACTION_MAX_LEN
            ),
            pressure_per_pending=_num(weights.get("pressure_per_pending"), GATING_PRESSURE_PER_PENDING),
            pressure_cap=_num(weights.get("pressure_cap"), GATING_PRESSURE_CAP),
            presence_penalty_max=_num(weights.get("presence_penalty_max"), GATING_PRESENCE_PENALTY_MAX),
            frequency_min=_num(weights.get("frequency_min"), GATING_FREQUENCY_MIN),
            frequency_max=_num(weights.get("frequency_max"), GATING_FREQUENCY_MAX),
            question_markers=tuple(markers.get("question", ())),
            request_markers=tuple(markers.get("request", ())),
            consult_markers=tuple(markers.get("consult", ())),
            llm_judge_max_per_minute=_int(config.get("llm_judge_max_per_minute"), 10),
            hybrid_escalate_band=_num(config.get("hybrid_escalate_band"), 20.0),
        )
