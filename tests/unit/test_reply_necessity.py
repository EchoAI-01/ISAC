"""ReplyNecessityJudge 单元测试 (DEVELOP.md 5.2 / ARCHITECTURE.md 3.7)。"""

from __future__ import annotations

from isac.core.constants import REPLY_NECESSITY_THRESHOLD
from isac.core.types import GatingContext
from isac.gateway.models import Session
from isac.gating.reply_necessity import ReplyNecessityJudge
from tests.fixtures.messages import make_isac_message

# 中性填充语：> 5 字且不含 问题/请求/征询 关键词，内容分为 0
NEUTRAL = "今天出去玩了一整天"


def _context(
    content: str = NEUTRAL,
    *,
    group_id: str | None = "group_001",
    has_at: bool = False,
    has_mention: bool = False,
    is_private: bool = False,
    focus_active: bool = False,
    pending_count: int = 0,
    effective_frequency: float = 1.0,
    recent_self_replies: int = 0,
    recent_window_messages: int = 0,
) -> GatingContext:
    message = make_isac_message(content=content, group_id=group_id)
    session = Session(session_id="sess_001", user_id="user_001", platform="qq", group_id=group_id)
    return GatingContext(
        session=session,
        user_profile=None,
        current_message=message,
        pending_count=pending_count,
        has_at=has_at,
        has_mention=has_mention,
        is_private=is_private,
        effective_frequency=effective_frequency,
        recent_self_replies=recent_self_replies,
        recent_window_messages=recent_window_messages,
        focus_active=focus_active,
    )


class TestBaseScore:
    async def test_at_highest(self):
        judge = ReplyNecessityJudge()
        # 基础 100 + 问题("在吗"含"吗")15 = 115
        score = await judge.score([], _context("在吗", has_at=True))
        assert score == 115.0
        assert score >= REPLY_NECESSITY_THRESHOLD

    async def test_mention_reaches_threshold(self):
        judge = ReplyNecessityJudge()
        score = await judge.score([], _context(has_mention=True))
        assert score == 80.0
        assert score >= REPLY_NECESSITY_THRESHOLD

    async def test_private_base(self):
        judge = ReplyNecessityJudge()
        score = await judge.score([], _context(group_id=None, is_private=True))
        assert score == 40.0

    async def test_focus_base(self):
        judge = ReplyNecessityJudge()
        score = await judge.score([], _context(focus_active=True))
        assert score == 40.0

    async def test_plain_group_message_low(self):
        judge = ReplyNecessityJudge()
        score = await judge.score([], _context())
        assert score == 0.0
        assert score < REPLY_NECESSITY_THRESHOLD


class TestContentScore:
    async def test_question_bonus(self):
        judge = ReplyNecessityJudge()
        score = await judge.score([], _context("今天天气怎么样"))
        assert score == 15.0

    async def test_request_bonus(self):
        judge = ReplyNecessityJudge()
        score = await judge.score([], _context("帮我查下资料"))
        assert score == 20.0

    async def test_consult_needs_mention(self):
        judge = ReplyNecessityJudge()
        # "你觉得这个方案好" 含征询词但无疑问词
        without = await judge.score([], _context("你觉得这个方案好"))
        with_mention = await judge.score([], _context("你觉得这个方案好", has_mention=True))
        assert without == 0.0  # 未提及：征询不加分
        assert with_mention == 100.0  # 基础 mention 80 + 征询 20

    async def test_short_reaction_penalty(self):
        judge = ReplyNecessityJudge()
        # 群聊短反应，基础 0 + 短反应 -25 → clamp 到 0
        score = await judge.score([], _context("哈哈"))
        assert score == 0.0

    async def test_short_reaction_not_applied_to_question(self):
        judge = ReplyNecessityJudge()
        # "为什么" 虽短但含疑问词 → 计问题分 +15，不计短反应
        score = await judge.score([], _context("为什么"))
        assert score == 15.0

    async def test_long_text_bonus(self):
        judge = ReplyNecessityJudge()
        assert await judge.score([], _context("a" * 121)) == 5.0
        assert await judge.score([], _context("a" * 241)) == 10.0


class TestPressureAndPenalty:
    async def test_pressure_linear_and_cap(self):
        judge = ReplyNecessityJudge()
        assert await judge.score([], _context(pending_count=3)) == 45.0
        assert await judge.score([], _context(pending_count=100)) == 100.0  # 封顶

    async def test_presence_penalty(self):
        judge = ReplyNecessityJudge()
        # 基础 mention 80 - 存在感惩罚(占比 1.0 → -25) = 55
        score = await judge.score(
            [],
            _context(has_mention=True, recent_self_replies=10, recent_window_messages=10),
        )
        assert score == 55.0

    async def test_pressure_pushes_plain_message_over_threshold(self):
        judge = ReplyNecessityJudge()
        # 普通群聊消息在积压足够时也可触发 (0 + 6×15=90)
        score = await judge.score([], _context(pending_count=6))
        assert score >= REPLY_NECESSITY_THRESHOLD


class TestFrequencyCoefficient:
    async def test_frequency_scales_and_clamps(self):
        judge = ReplyNecessityJudge()
        # mention 80 × 0.5 = 40
        assert await judge.score([], _context(has_mention=True, effective_frequency=0.5)) == 40.0
        # 超出上限被 clamp 到 1.0 → 80
        assert await judge.score([], _context(has_mention=True, effective_frequency=5.0)) == 80.0
        # 低于下限被 clamp 到 0.5 → 40
        assert await judge.score([], _context(has_mention=True, effective_frequency=0.1)) == 40.0
