"""core/types 单元测试。"""

from __future__ import annotations

from types import SimpleNamespace

from isac.core.types import (
    AgentContext,
    Budget,
    GatingContext,
    InjectionContext,
    MessageStatus,
    TokenUsage,
)


class TestBudget:
    def test_remaining_initial(self):
        budget = Budget()
        assert budget.remaining is True
        assert budget.remaining_tokens == 8000

    def test_consume_iterations(self):
        budget = Budget(max_iterations=2, remaining_iterations=2)
        budget.consume(TokenUsage(total_tokens=100))
        assert budget.remaining is True
        budget.consume(TokenUsage(total_tokens=100))
        assert budget.remaining is False  # 迭代耗尽

    def test_consume_tokens(self):
        budget = Budget(max_tokens=100)
        budget.consume(TokenUsage(total_tokens=150))
        assert budget.remaining_tokens == 0
        assert budget.remaining is False  # token 耗尽


class TestMessageStatus:
    def test_values(self):
        assert MessageStatus.RECEIVED.value == "received"
        assert MessageStatus.DROPPED.value == "dropped"


class TestTokenUsage:
    def test_total_auto_calculated(self):
        usage = TokenUsage(prompt_tokens=10, completion_tokens=5)
        assert usage.total_tokens == 15

    def test_total_preserved_when_non_zero(self):
        usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=100)
        assert usage.total_tokens == 100

    def test_budget_consume_uses_total(self):
        budget = Budget(max_tokens=100)
        budget.consume(TokenUsage(prompt_tokens=30, completion_tokens=20))
        assert budget.used_tokens == 50
        assert budget.remaining_tokens == 50

    def test_detail_token_fields_default_to_zero(self):
        """J1: cache/reasoning/audio 明细字段默认 0, 不影响 total_tokens 自动计算。"""
        usage = TokenUsage(prompt_tokens=10, completion_tokens=5)
        assert usage.cache_read_tokens == 0
        assert usage.cache_write_tokens == 0
        assert usage.reasoning_tokens == 0
        assert usage.audio_input_tokens == 0
        assert usage.audio_output_tokens == 0
        assert usage.total_tokens == 15

    def test_detail_token_fields_can_be_set(self):
        usage = TokenUsage(
            prompt_tokens=100,
            completion_tokens=50,
            cache_read_tokens=80,
            reasoning_tokens=20,
            audio_input_tokens=5,
            audio_output_tokens=3,
        )
        assert usage.cache_read_tokens == 80
        assert usage.reasoning_tokens == 20
        assert usage.audio_input_tokens == 5
        assert usage.audio_output_tokens == 3


class TestContexts:
    def _session(self):
        return SimpleNamespace(session_id="sess_001", agent_id="agent_a")

    def _message(self):
        return SimpleNamespace(content="hi", platform="qq")

    def test_injection_context_defaults(self):
        ctx = InjectionContext(session=self._session(), user_profile=None, current_message=self._message())
        assert ctx.available_prompt_tokens == 8000

    def test_agent_context_budget(self):
        ctx = AgentContext(session=self._session(), user_profile=None, current_message=self._message())
        assert ctx.budget.remaining is True
        assert ctx.iteration == 0

    def test_gating_context_flags(self):
        ctx = GatingContext(
            session=self._session(),
            user_profile=None,
            current_message=self._message(),
            has_at=True,
        )
        assert ctx.has_at is True
        assert ctx.focus_active is False
