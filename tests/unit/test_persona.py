"""Persona (MoodEngine / BehaviorLearner) 单元测试 (D8, ARCHITECTURE.md 3.8)。"""

from __future__ import annotations

import pytest

from isac.agent.hooks import AgentHooks
from isac.core.events import AgentHookPoint
from isac.core.types import AgentContext, LLMResponse, TokenUsage, ToolCall
from isac.gateway.models import Session, UserProfile
from isac.persona.behavior_learner import MAX_PATTERNS, BehaviorLearner
from isac.persona.manager import PersonaManager
from isac.persona.mood import MoodEngine
from isac.persona.mood_tracker import AROUSAL_STEP_PER_TOOL_CALL, MAX_TOOL_CALLS_COUNTED, MoodTracker


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


class TestMoodTracker:
    """MoodTracker: MoodEngine 生产接入 (Q2 激活)。"""

    def _make_context(self, tool_calls_this_turn: int = 0) -> AgentContext:
        return AgentContext(
            session=Session(session_id="s1", user_id="u1", platform="qq"),
            user_profile=None,
            current_message=object(),
            tool_calls_this_turn=tool_calls_this_turn,
        )

    @pytest.mark.asyncio
    async def test_no_tool_calls_only_decays(self):
        """无工具调用: 只 decay, 不额外扰动 (数值同 test_decay_moves_toward_neutral)。"""
        engine = MoodEngine(decay_rate=0.5)
        engine.update(valence_delta=1.0, arousal_delta=0.5)  # excited
        tracker = MoodTracker(engine)
        response = LLMResponse(content="ok", usage=TokenUsage())
        await tracker._on_final_response(response, self._make_context())  # noqa: SLF001
        state = engine.current()
        assert abs(state.valence - 0.5) < 1e-9
        assert abs(state.arousal - 0.75) < 1e-9
        assert state.label == "excited"

    @pytest.mark.asyncio
    async def test_tool_calls_add_small_arousal_bump(self):
        """本轮工具调用越多 (读 context.tool_calls_this_turn——FINAL_RESPONSE 触发时
        response.tool_calls 恒为空, 不能从 response 上取), decay 之后再叠加的
        arousal 扰动越大 (仍很小幅)。"""
        engine = MoodEngine()  # decay_rate=0.05, 起点中性 (0.0, 0.5)
        tracker = MoodTracker(engine)
        response = LLMResponse(content="ok", usage=TokenUsage())
        ctx = self._make_context(tool_calls_this_turn=2)
        await tracker._on_final_response(response, ctx)  # noqa: SLF001
        state = engine.current()
        # decay 先把中性态原地不变 (valence=0, arousal=0.5); 再叠加 2 次工具调用扰动
        assert abs(state.valence - 0.0) < 1e-9
        assert abs(state.arousal - (0.5 + AROUSAL_STEP_PER_TOOL_CALL * 2)) < 1e-9

    @pytest.mark.asyncio
    async def test_tool_call_count_capped(self):
        """单轮工具调用数超过上限时封顶, 避免工具风暴过度推高情绪。"""
        engine = MoodEngine()
        tracker = MoodTracker(engine)
        response = LLMResponse(content="ok", usage=TokenUsage())
        ctx = self._make_context(tool_calls_this_turn=MAX_TOOL_CALLS_COUNTED + 3)
        await tracker._on_final_response(response, ctx)  # noqa: SLF001
        state = engine.current()
        assert abs(state.arousal - (0.5 + AROUSAL_STEP_PER_TOOL_CALL * MAX_TOOL_CALLS_COUNTED)) < 1e-9

    @pytest.mark.asyncio
    async def test_register_hooks_fires_on_final_response(self):
        """经 register_hooks 挂到 AgentHooks 后, FINAL_RESPONSE 真实触发 decay。"""
        engine = MoodEngine(decay_rate=0.5)
        engine.update(valence_delta=1.0, arousal_delta=0.5)  # excited
        tracker = MoodTracker(engine)
        hooks = AgentHooks()
        tracker.register_hooks(hooks)

        response = LLMResponse(content="ok", usage=TokenUsage())
        for hook in hooks.get_hooks(AgentHookPoint.FINAL_RESPONSE):
            await hook(response, self._make_context())

        state = engine.current()
        assert state.valence < 1.0  # 已衰减, 不再钉在极值

    @pytest.mark.asyncio
    async def test_real_loop_drives_arousal_bump_end_to_end(self):
        """回归防护: 只在单测里手工构造 LLMResponse(tool_calls=[...]) 直调
        _on_final_response 曾经全绿, 但生产环境 FINAL_RESPONSE 触发时
        response.tool_calls 恒为空 (isac/agent/loop.py 的 else 分支正是靠
        "无 tool_calls" 才进入 FINAL_RESPONSE), 那条读法是死代码。这里跑真实
        ISACAgentLoop (一次工具调用 + 一次最终回复), 证明 arousal 真的被推高。"""
        from isac.agent.loop import ISACAgentLoop
        from isac.agent.prompt_builder import SystemPromptBuilder
        from isac.agent.tools.base import Tool, ToolContext
        from isac.agent.tools.registry import ToolRegistry
        from isac.core.types import ToolResult

        class _ToolCallingProvider:
            def __init__(self) -> None:
                self.calls = 0

            async def chat(self, system, messages, tools=None, **kwargs):  # noqa: ANN001, ARG002
                self.calls += 1
                if self.calls == 1:
                    return LLMResponse(
                        content="",
                        tool_calls=[ToolCall(id="t1", name="noop", arguments={})],
                        usage=TokenUsage(total_tokens=1),
                    )
                return LLMResponse(content="done", usage=TokenUsage(total_tokens=1))

            def chat_stream(self, *args, **kwargs):  # noqa: ANN002, ANN003
                raise NotImplementedError

            def get_model_name(self) -> str:
                return "test"

            def get_capabilities(self):
                return None

        class _NoopTool(Tool):
            @property
            def name(self) -> str:
                return "noop"

            @property
            def description(self) -> str:
                return "noop"

            async def execute(self, context: ToolContext) -> ToolResult:  # noqa: ARG002
                return ToolResult(content="ok")

        engine = MoodEngine()  # 起点中性 (0.0, 0.5)
        manager = PersonaManager({}, {}, mood_engine=engine)
        hooks = AgentHooks()
        manager.register_hooks(hooks)
        registry = ToolRegistry()
        registry.register(_NoopTool())
        loop = ISACAgentLoop(
            llm=_ToolCallingProvider(),
            prompt_builder=SystemPromptBuilder(),
            hooks=hooks,
            tools=registry,
        )
        ctx = self._make_context()
        result = await loop.run([{"role": "user", "content": "hi"}], ctx)

        assert result.content == "done"
        assert ctx.tool_calls_this_turn == 1
        state = manager.current_mood()
        assert abs(state.arousal - (0.5 + AROUSAL_STEP_PER_TOOL_CALL)) < 1e-9


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

    @pytest.mark.asyncio
    async def test_register_hooks_attaches_mood_tracker(self):
        """Q2 激活: register_hooks 同时挂上 MoodTracker, FINAL_RESPONSE 后情绪真实衰减。"""
        engine = MoodEngine()
        engine.update(valence_delta=1.0, arousal_delta=0.5)  # excited
        manager = PersonaManager({}, {}, mood_engine=engine)
        hooks = AgentHooks()
        manager.register_hooks(hooks)

        response = LLMResponse(content="hello", usage=TokenUsage())
        ctx = AgentContext(
            session=Session(session_id="s1", user_id="u1", platform="qq"),
            user_profile=None,
            current_message=object(),
        )
        for hook in hooks.get_hooks(AgentHookPoint.FINAL_RESPONSE):
            await hook(response, ctx)

        state = manager.current_mood()
        assert abs(state.valence - 0.95) < 1e-9  # 1.0 * (1 - 0.05)
        assert abs(state.arousal - 0.975) < 1e-9  # 0.5 + (1.0 - 0.5) * (1 - 0.05)
