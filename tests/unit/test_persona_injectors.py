"""Q2 人格系统三个注入器 (Mood / ExpressionStyle / AttentionDrift) 单元测试。

验证:
- 注入器注册到 prompt_builder 后能产出非空提示文案
- 文案包含对应的核心字段 (情绪 label / 风格轴值 / 漂移档位)
- 无 mood_engine / 无 persona_manager 时返回空串 (零行为变化)
- UserProfile.expression_style 覆盖能合并进 ExpressionStyleInjector
- AttentionDriftInjector 不同 level 取出不同 i18n 文案
"""

from __future__ import annotations

import pytest

from isac.agent.injectors.attention_drift import AttentionDriftInjector
from isac.agent.injectors.expression_style import ExpressionStyleInjector
from isac.agent.injectors.mood import MoodInjector
from isac.core.types import InjectionContext
from isac.gateway.models import Session, UserProfile
from isac.persona.manager import PersonaManager
from isac.persona.mood import MoodEngine


class _Message:
    def __init__(self, content: str = "你好") -> None:
        self.content = content


def _ctx(*, profile: UserProfile | None = None) -> InjectionContext:
    return InjectionContext(
        session=Session(session_id="s1", user_id="u1", agent_id="a1"),
        user_profile=profile,
        current_message=_Message(),
    )


# ── MoodInjector ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mood_injector_renders_current_mood_label() -> None:
    """MoodInjector 读 MoodEngine 当前情绪 → 产出含 label + valence/arousal 的文案。"""
    engine = MoodEngine()
    engine.update(valence_delta=0.8, arousal_delta=0.1)  # happy (arousal=0.6, 不超 0.7 高激动阈值)
    injector = MoodInjector(mood_engine=engine)
    text = await injector.build(_ctx())
    assert "happy" in text
    assert "valence" in text
    assert "arousal" in text
    assert "+0.80" in text or "+0.8" in text


@pytest.mark.asyncio
async def test_mood_injector_returns_empty_when_no_engine() -> None:
    """无 MoodEngine 时返回空串 (零行为变化)。"""
    injector = MoodInjector(mood_engine=None)
    text = await injector.build(_ctx())
    assert text == ""


@pytest.mark.asyncio
async def test_mood_injector_reflects_engine_state_changes() -> None:
    """MoodEngine 状态变化后, 注入器文案随之更新 (不是缓存)。"""
    engine = MoodEngine()
    injector = MoodInjector(mood_engine=engine)

    engine.update(valence_delta=-0.8, arousal_delta=0.5)  # angry
    text_angry = await injector.build(_ctx())
    assert "angry" in text_angry

    engine.reset()
    text_neutral = await injector.build(_ctx())
    assert "neutral" in text_neutral


# ── ExpressionStyleInjector ──────────────────────────────────────


@pytest.mark.asyncio
async def test_expression_style_injector_renders_four_axes() -> None:
    """ExpressionStyleInjector 产出含 4 个风格轴 (formality/verbosity/humor/empathy) 的文案。"""
    persona = PersonaManager({"expression_style": {"formality": 0.8, "verbosity": 0.3, "humor": 0.6, "empathy": 0.9}})
    injector = ExpressionStyleInjector(persona_manager=persona)
    text = await injector.build(_ctx())
    assert "正式度" in text
    assert "详尽度" in text
    assert "幽默度" in text
    assert "共情度" in text
    assert "0.80" in text or "0.8" in text


@pytest.mark.asyncio
async def test_expression_style_injector_returns_empty_when_no_persona() -> None:
    """无 PersonaManager 时返回空串。"""
    injector = ExpressionStyleInjector(persona_manager=None)
    text = await injector.build(_ctx())
    assert text == ""


@pytest.mark.asyncio
async def test_expression_style_injector_merges_user_profile_override() -> None:
    """UserProfile.expression_style 覆盖能合并进风格 (用户侧 50% 权重)。"""
    persona = PersonaManager({"expression_style": {"formality": 0.8, "verbosity": 0.8, "humor": 0.8, "empathy": 0.8}})
    injector = ExpressionStyleInjector(persona_manager=persona)
    profile = UserProfile(
        user_id="u1",
        expression_style={"formality": 0.2, "verbosity": 0.2, "humor": 0.2, "empathy": 0.2},
    )
    text = await injector.build(_ctx(profile=profile))
    # 用户偏好 (0.2) + 全局 (0.8) / 2 = 0.5 (中性)
    assert "0.50" in text or "0.5" in text


@pytest.mark.asyncio
async def test_expression_style_injector_ignores_invalid_user_override() -> None:
    """UserProfile.expression_style 含非法值时降级用全局风格 (不抛异常)。"""
    persona = PersonaManager({"expression_style": {"formality": 0.5, "verbosity": 0.5, "humor": 0.5, "empathy": 0.5}})
    injector = ExpressionStyleInjector(persona_manager=persona)
    profile = UserProfile(user_id="u1", expression_style={"formality": "not-a-number"})
    text = await injector.build(_ctx(profile=profile))
    assert "正式度" in text  # 降级到全局 0.5, 不崩


# ── AttentionDriftInjector ───────────────────────────────────────


@pytest.mark.asyncio
async def test_attention_drift_injector_renders_level_and_anchor_policy() -> None:
    """AttentionDriftInjector 产出含档位 + i18n 文案 + 锚点策略的提示。"""
    injector = AttentionDriftInjector(level="wild")
    text = await injector.build(_ctx())
    assert "wild" in text
    assert "狂野" in text  # i18n zh_CN 默认文案
    assert "loose" in text  # 锚点策略


@pytest.mark.asyncio
async def test_attention_drift_injector_subtle_level_uses_strict_anchor() -> None:
    """subtle 档位对应 strict 锚点策略 (漂移后尽快回归原话题)。"""
    injector = AttentionDriftInjector(level="subtle")
    text = await injector.build(_ctx())
    assert "subtle" in text
    assert "轻微" in text  # i18n zh_CN
    assert "strict" in text


@pytest.mark.asyncio
async def test_attention_drift_injector_unknown_level_falls_back_to_subtle() -> None:
    """未识别的 level 降级到 subtle (DRIFT_PROFILES.get(...) or DRIFT_PROFILES['subtle'])。"""
    injector = AttentionDriftInjector(level="nonexistent")
    text = await injector.build(_ctx())
    # 降级到 subtle 的 i18n 文案
    assert "轻微" in text
    # 文档位显示传入的 level, 但锚点策略走 subtle 的 strict
    assert "strict" in text


# ── 集成: assembly.py 真实注册 3 个注入器 ─────────────────────────


@pytest.mark.asyncio
async def test_assembly_registers_persona_injectors_into_prompt_builder() -> None:
    """assemble_agent 后 prompt_builder 含 mood_system / expression_style /
    attention_drift 三个注入器 (Q2 接入点)。"""
    from isac.memory.pipeline import NoOpMemoryPipeline
    from isac.provider.llm.stub import StubProvider
    from isac.provider.manager import ProviderManager
    from isac.runtime.assembly import assemble_agent
    from isac.runtime.config import AgentConfig

    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    instance = await assemble_agent(
        AgentConfig(agent_id="q2_test", persona={}),
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        },
    )
    keys = [inj.key for inj in instance.prompt_builder._injectors]  # type: ignore[attr-defined]
    assert "mood_system" in keys
    assert "expression_style" in keys
    assert "attention_drift" in keys


def _find_injector(instance, key: str):
    for inj in instance.prompt_builder._injectors:  # type: ignore[attr-defined]
        if inj.key == key:
            return inj
    raise AssertionError(f"未找到注入器 key={key!r}")


@pytest.mark.asyncio
async def test_assembly_wires_persona_description_into_base_identity() -> None:
    """Q2 激活: config.persona.description 接入 BaseIdentityInjector, 不同 Agent
    的人格文本在 System Prompt 中可辨。"""
    from isac.memory.pipeline import NoOpMemoryPipeline
    from isac.provider.llm.stub import StubProvider
    from isac.provider.manager import ProviderManager
    from isac.runtime.assembly import assemble_agent
    from isac.runtime.config import AgentConfig

    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    instance = await assemble_agent(
        AgentConfig(agent_id="q2_persona_test", persona={"description": "你是爱丽丝，古灵精怪的猫娘助理。"}),
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        },
    )
    injector = _find_injector(instance, "base_identity")
    text = await injector.build(_ctx())
    assert text == "你是爱丽丝，古灵精怪的猫娘助理。"


@pytest.mark.asyncio
async def test_assembly_base_identity_falls_back_without_persona_description() -> None:
    """未配置 persona.description 时回落默认文案 (零行为变化)。"""
    from isac.memory.pipeline import NoOpMemoryPipeline
    from isac.provider.llm.stub import StubProvider
    from isac.provider.manager import ProviderManager
    from isac.runtime.assembly import assemble_agent
    from isac.runtime.config import AgentConfig

    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    instance = await assemble_agent(
        AgentConfig(agent_id="q2_no_persona_test", persona={}),
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        },
    )
    injector = _find_injector(instance, "base_identity")
    text = await injector.build(_ctx())
    assert text == "你是 ISAC，一个智能社交陪伴 AI。"


@pytest.mark.asyncio
async def test_assembly_global_persona_description_used_when_agent_level_absent() -> None:
    """全局 persona.description 兜底; Agent 级配置存在时优先 Agent 级。"""
    from isac.memory.pipeline import NoOpMemoryPipeline
    from isac.provider.llm.stub import StubProvider
    from isac.provider.manager import ProviderManager
    from isac.runtime.assembly import assemble_agent
    from isac.runtime.config import AgentConfig

    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    instance = await assemble_agent(
        AgentConfig(agent_id="q2_global_persona_test", persona={}),
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {"persona": {"description": "全局默认人设文案"}},
        },
    )
    injector = _find_injector(instance, "base_identity")
    text = await injector.build(_ctx())
    assert text == "全局默认人设文案"
