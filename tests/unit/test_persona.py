"""Persona (MoodEngine / BehaviorLearner) 单元测试 (D8, ARCHITECTURE.md 3.8)。"""

from __future__ import annotations

import pytest

from isac.agent.hooks import AgentHooks
from isac.core.events import AgentHookPoint
from isac.core.types import AgentContext, LLMResponse, TokenUsage
from isac.gateway.models import Session, UserProfile
from isac.persona.behavior_learner import MAX_PATTERNS, BehaviorLearner
from isac.persona.manager import PersonaManager
from isac.persona.mood import MoodEngine


class TestMoodEngine:
    def test_default_state_is_neutral(self):
        engine = MoodEngine()
        state = engine.current()
        assert state.valence == 0.0
        assert state.arousal == 0.5
        assert state.label == "neutral"

    def test_update_clamps_to_bounds(self):
        engine = MoodEngine()
        engine.update(valence_delta=5.0, arousal_delta=10.0)
        state = engine.current()
        assert state.valence == 1.0
        assert state.arousal == 1.0
        assert state.label == "excited"

    def test_update_negative_emotion(self):
        engine = MoodEngine()
        engine.update(valence_delta=-0.8, arousal_delta=0.5)
        state = engine.current()
        assert state.valence == -0.8
        assert state.arousal == 1.0
        assert state.label == "angry"

    def test_decay_moves_toward_neutral(self):
        engine = MoodEngine(decay_rate=0.5)
        engine.update(valence_delta=1.0, arousal_delta=0.5)  # valence=1, arousal=1 → excited
        engine.decay()
        state = engine.current()
        # valence: 1 * 0.5 = 0.5; arousal: 0.5 + (1 - 0.5) * 0.5 = 0.75 → 仍 excited
        assert abs(state.valence - 0.5) < 1e-9
        assert abs(state.arousal - 0.75) < 1e-9
        assert state.label == "excited"
        # 再 decay 一次: valence=0.25, arousal=0.625 → happy
        engine.decay()
        state = engine.current()
        assert abs(state.valence - 0.25) < 1e-9
        assert abs(state.arousal - 0.625) < 1e-9
        assert state.label == "happy"

    def test_decay_with_zero_rate_keeps_state(self):
        engine = MoodEngine(decay_rate=0)
        engine.update(valence_delta=0.5)
        before = engine.current()
        engine.decay()
        after = engine.current()
        assert before.valence == after.valence
        assert before.arousal == after.arousal

    def test_reset(self):
        engine = MoodEngine()
        engine.update(valence_delta=1.0)
        engine.reset()
        state = engine.current()
        assert state.valence == 0.0
        assert state.label == "neutral"


class TestBehaviorLearner:
    def _make_context(self, profile: UserProfile | None = None) -> AgentContext:
        return AgentContext(
            session=Session(session_id="s1", user_id="u1", platform="qq"),
            user_profile=profile,
            current_message=object(),
        )

    @pytest.mark.asyncio
    async def test_no_profile_does_not_throw(self):
        learner = BehaviorLearner()
        hooks = AgentHooks()
        learner.register_hooks(hooks)
        response = LLMResponse(content="hello", usage=TokenUsage())
        ctx = self._make_context(profile=None)
        # 不应抛异常
        for hook in hooks.get_hooks(AgentHookPoint.FINAL_RESPONSE):
            await hook(response, ctx)

    @pytest.mark.asyncio
    async def test_records_pattern_on_final_response(self):
        profile = UserProfile(user_id="u1")
        learner = BehaviorLearner()
        hooks = AgentHooks()
        learner.register_hooks(hooks)

        response = LLMResponse(content="好的，我看看🤔👍", usage=TokenUsage())
        ctx = self._make_context(profile=profile)

        for hook in hooks.get_hooks(AgentHookPoint.FINAL_RESPONSE):
            await hook(response, ctx)

        assert len(profile.behavior_patterns) == 1
        pattern = profile.behavior_patterns[0]
        assert pattern["length"] == len("好的，我看看🤔👍")
        assert pattern["emoji_count"] == 2  # 🤔 与 👍
        assert pattern["length_bucket"] in ("short", "medium", "long", "very_long")

    @pytest.mark.asyncio
    async def test_pattern_overflow_drops_oldest(self):
        profile = UserProfile(user_id="u1")
        learner = BehaviorLearner(max_patterns=3)
        hooks = AgentHooks()
        learner.register_hooks(hooks)

        for i in range(5):
            response = LLMResponse(content=f"reply {i}", usage=TokenUsage())
            ctx = self._make_context(profile=profile)
            for hook in hooks.get_hooks(AgentHookPoint.FINAL_RESPONSE):
                await hook(response, ctx)

        assert len(profile.behavior_patterns) == 3
        # 最旧的 "reply 0" 应已被丢弃
        hints = [p["topic_hint"] for p in profile.behavior_patterns]
        assert "reply 0" not in hints and "reply 1" not in hints
        assert "reply 2" in hints and "reply 4" in hints

    def test_default_max_patterns_constant(self):
        assert MAX_PATTERNS >= 5


class TestPersonaManager:
    def test_default_expression_style(self):
        manager = PersonaManager({}, {})
        style = manager.get_expression_style()
        assert style.formality == 0.5
        assert style.empathy == 0.7

    def test_agent_override_merges(self):
        manager = PersonaManager(
            {"expression_style": {"formality": 0.8, "humor": 0.2}},
            {"expression_style": {"humor": 0.9}},
        )
        style = manager.get_expression_style()
        assert style.formality == 0.8  # 全局保留
        assert style.humor == 0.9  # Agent 覆盖

    def test_default_drift_level(self):
        manager = PersonaManager({}, {})
        assert manager.get_drift_level() == "subtle"

    def test_mood_engine_attached(self):
        engine = MoodEngine()
        engine.update(valence_delta=0.5)
        manager = PersonaManager({}, {}, mood_engine=engine)
        assert manager.current_mood().valence == 0.5

    @pytest.mark.asyncio
    async def test_register_hooks_attaches_behavior_learner(self):
        profile = UserProfile(user_id="u1")
        manager = PersonaManager({}, {})
        hooks = AgentHooks()
        manager.register_hooks(hooks)

        response = LLMResponse(content="hello", usage=TokenUsage())
        ctx = AgentContext(
            session=Session(session_id="s1", user_id="u1", platform="qq"),
            user_profile=profile,
            current_message=object(),
        )
        for hook in hooks.get_hooks(AgentHookPoint.FINAL_RESPONSE):
            await hook(response, ctx)
        assert len(profile.behavior_patterns) == 1
