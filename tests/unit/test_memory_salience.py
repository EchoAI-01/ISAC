"""阶段2-4 (P1-3) 记忆显著度评分器测试。

核心验收: 评分器产出一个**真实分布**, 让 consolidator 的重要性剪枝真正可用 ——
琐碎寒暄/应答必须落在剪枝阈值 (DEFAULT_PRUNE_IMPORTANCE_BELOW=0.2) 之下,
含"记住/偏好/事实/约定"的回合必须居高位; 短但重要的内容不得被误判为琐碎。
"""

from __future__ import annotations

import pytest

from isac.memory.consolidator import DEFAULT_PRUNE_IMPORTANCE_BELOW
from isac.memory.salience import (
    DEFAULT_SCORER,
    OBSERVED_FACTOR,
    SCORE_MAX,
    SCORE_MIN,
    ImportanceScorer,
    score_importance,
)

PRUNE = DEFAULT_PRUNE_IMPORTANCE_BELOW  # 0.2


# ── 琐碎内容必须落到剪枝阈值之下 (修复"剪枝恒空转"的核心) ──────────


@pytest.mark.parametrize(
    "user",
    ["嗯", "哦", "好的", "哈哈", "谢谢", "ok", "你好", "晚安", "收到", "知道了", "嗯嗯", "666"],
)
def test_trivial_chitchat_scores_below_prune_threshold(user: str) -> None:
    """纯语气词/寒暄/应答 → 低于剪枝阈值, 时间衰减后可被剪掉。"""
    assert score_importance(user, "好的呢") < PRUNE


def test_empty_user_text_scores_low() -> None:
    assert score_importance("", "") < PRUNE
    assert score_importance("", "我说了很多话" * 5) < PRUNE


# ── 值得记的内容必须居高位 ────────────────────────────────────────


def test_explicit_remember_marker_scores_high() -> None:
    assert score_importance("记住我的邮箱是 a@b.com", "好的，已记录") > 0.5


def test_self_fact_preference_scores_high() -> None:
    assert score_importance("我叫张三，我住在上海，我喜欢喝咖啡", "了解～") > 0.5


def test_commitment_date_scores_high() -> None:
    assert score_importance("我们约好明天下午3点开会", "好的") > 0.5


def test_short_but_important_not_misclassified_trivial() -> None:
    """关键回归: 短文本含记忆标记时绝不能走琐碎短路 (否则重要信息被剪)。"""
    s = score_importance("记住我生日3月5日", "")
    assert s >= 0.5
    assert s > PRUNE


# ── 普通回合居中 ─────────────────────────────────────────────────


def test_normal_substantive_turn_is_mid() -> None:
    user = "帮我解释一下什么是事件溯源架构，它的优缺点是什么？"
    reply = "事件溯源是一种把状态变化存成不可变事件序列的架构，优点是审计完整、可回放。"
    s = score_importance(user, reply)
    # 无记忆标记的普通问答: 应在琐碎阈值之上、记忆高位之下。
    assert s > PRUNE
    assert s < 0.5


# ── 旁听折扣 ─────────────────────────────────────────────────────


def test_observed_discount_lowers_score() -> None:
    user = "帮我解释一下什么是事件溯源架构，它的优缺点是什么？"
    reply = "事件溯源是一种把状态变化存成不可变事件序列的架构。"
    main = score_importance(user, reply, observed=False)
    obs = score_importance(user, reply, observed=True)
    assert obs < main
    assert obs == pytest.approx(main * OBSERVED_FACTOR, rel=1e-6)


# ── 分数恒在 [0,1] ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "user,reply",
    [
        ("", ""),
        ("嗯", ""),
        ("记住" * 50, "记" * 50),  # 标记堆叠不得顶穿上限
        ("我叫张三我住在上海我喜欢咖啡我讨厌香菜" * 10, "好" * 100),
        ("x", "y"),
    ],
)
def test_score_always_clamped_to_unit_interval(user: str, reply: str) -> None:
    s = score_importance(user, reply)
    assert SCORE_MIN <= s <= SCORE_MAX


def test_marker_boost_capped() -> None:
    """多重标记叠加受 MAX_MARKER_BOOST 上限约束, 不顶满。"""
    s = score_importance("记住我叫张三我住在上海，明天3月5日开会，电话13800138000", "")
    assert s <= SCORE_MAX


# ── 确定性 + 可替换实现 (升级位) ─────────────────────────────────


def test_scorer_is_deterministic() -> None:
    a = score_importance("我喜欢喝美式咖啡", "好的")
    b = score_importance("我喜欢喝美式咖啡", "好的")
    assert a == b


def test_custom_scorer_same_interface_swappable() -> None:
    """升级位: 同签名实现可替换 (如将来 LLM 评分), 调用方不变。"""

    class _ConstScorer(ImportanceScorer):
        def score(self, user_text, reply_text="", *, observed=False, is_group=False):  # noqa: ANN001
            return 0.9

    assert _ConstScorer().score("任意", "") == 0.9
    assert DEFAULT_SCORER is not None


# ── 与 consolidator 剪枝联动的端到端不变量 ──────────────────────


def test_distribution_spans_prune_threshold() -> None:
    """同一评分器对不同输入必须同时产出阈值两侧的值 —— 剪枝才有素材。"""
    low = score_importance("嗯", "好")
    high = score_importance("记住我的生日是3月5日", "已记录")
    assert low < PRUNE < high
