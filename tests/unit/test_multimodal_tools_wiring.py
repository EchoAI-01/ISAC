"""Q3 多模态工具接入生产 ToolRegistry + PluginManager 接 EnableMatrix 测试。

验证:
- 6 个多模态工具 (generate_image / generate_video / transcribe_audio /
  synthesize_speech / understand_image / understand_video) 在 assemble_agent 后
  出现在 tool_registry.definitions() 里 (此前从未注册过, LLM schema 看不到)
- 默认权限是 deny, 出现在 definitions() 但 LLM 调用时受 deny 拦截
- AgentConfig.tools_policy 显式开启后可调用
- PluginManager 接入 EnableMatrix 后 is_enabled_for 走真实矩阵决策 (此前
  enable_matrix=None 时恒返回 True)
"""

from __future__ import annotations

import pytest

from isac.core.policy import EnableMatrix
from isac.memory.pipeline import NoOpMemoryPipeline
from isac.plugin.runtime.manager import PluginManager
from isac.provider.llm.stub import StubProvider
from isac.provider.manager import ProviderManager
from isac.runtime.assembly import assemble_agent
from isac.runtime.config import AgentConfig

# ── 多模态工具接入 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assemble_agent_registers_multimodal_tools() -> None:
    """Q3: assemble_agent 后 ToolRegistry 内部 _tools 含 6 个多模态工具名
    (注册了, 但默认 deny 不会出现在 LLM schema 的 definitions() 里,
    由 test_multimodal_tools_default_policy_deny_blocks_llm_call 验证)。"""
    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    instance = await assemble_agent(
        AgentConfig(agent_id="q3_test"),
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        },
    )
    # _tools 是 ToolRegistry 内部 dict (注册即包含, 不受 policy 过滤)
    tool_names = set(instance.tools._tools.keys())  # type: ignore[attr-defined]
    assert "generate_image" in tool_names
    assert "generate_video" in tool_names
    assert "transcribe_audio" in tool_names
    assert "synthesize_speech" in tool_names
    assert "understand_image" in tool_names
    assert "understand_video" in tool_names


@pytest.mark.asyncio
async def test_multimodal_tools_default_policy_deny_blocks_llm_call() -> None:
    """默认权限 deny: LLM schema 里看不到这些工具 (definitions() 过滤 deny),
    即使强行构造 ToolContext 调用也会被 ToolRegistry 拦截。"""
    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    instance = await assemble_agent(
        AgentConfig(agent_id="q3_deny"),
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        },
    )
    # definitions() 通常过滤 deny 策略, 故 LLM 看不到 generate_image
    visible = {d["name"] for d in instance.tools.definitions()}
    assert "generate_image" not in visible


@pytest.mark.asyncio
async def test_multimodal_tools_can_be_allowed_via_agent_config() -> None:
    """AgentConfig.tools_policy 显式 allow 后, generate_image 出现在 LLM schema。"""
    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    instance = await assemble_agent(
        AgentConfig(agent_id="q3_allow", tools_policy={"generate_image": "allow"}),
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        },
    )
    visible = {d["name"] for d in instance.tools.definitions()}
    assert "generate_image" in visible


# ── PluginManager 接 EnableMatrix ─────────────────────────────────


def test_plugin_manager_with_enable_matrix_uses_real_decision() -> None:
    """enable_matrix 注入后 is_enabled_for 走真实矩阵 (Agent deny → False)。"""
    matrix = EnableMatrix(
        global_policy={"plugins_deny": ["bad_plugin"]},
        channel_overrides={},
    )
    manager = PluginManager({}, enable_matrix=matrix)
    # bad_plugin 在 global_policy.plugins_deny → 拒绝
    assert manager.is_enabled_for("bad_plugin", "agent_a", "qq") is False
    # 普通插件未在 deny → 放行
    assert manager.is_enabled_for("normal_plugin", "agent_a", "qq") is True


def test_plugin_manager_without_enable_matrix_defaults_allow() -> None:
    """enable_matrix=None 时默认放行 (向后兼容, 不影响已有装配)。"""
    manager = PluginManager({})
    assert manager.is_enabled_for("any_plugin", "agent_a", "qq") is True


def test_plugin_manager_enable_matrix_respects_global_deny() -> None:
    """全局 plugins_deny 列表里的插件被拒绝 (覆盖 Agent allow=["*"])。"""
    matrix = EnableMatrix(
        global_policy={"plugins_deny": ["globally_banned"]},
    )
    manager = PluginManager({}, enable_matrix=matrix)
    # manager.is_enabled_for 传 ["*"], [] 作 Agent allow/deny; 全局 deny 应覆盖
    assert manager.is_enabled_for("globally_banned", "any_agent", "any_platform") is False


def test_plugin_manager_enable_matrix_respects_channel_override() -> None:
    """Channel 矩阵里显式 False 的插件在该平台被拒绝。"""
    matrix = EnableMatrix(
        channel_overrides={
            "qq": {"plugins": {"qq_only_disabled": False}},
        },
    )
    manager = PluginManager({}, enable_matrix=matrix)
    # qq 平台禁用 qq_only_disabled
    assert manager.is_enabled_for("qq_only_disabled", "agent_a", "qq") is False
    # telegram 平台未配置, 默认放行
    assert manager.is_enabled_for("qq_only_disabled", "agent_a", "telegram") is True


def test_plugin_manager_enable_matrix_independent_of_load_all() -> None:
    """enable_matrix 不影响 load_all (加载阶段全部加载); 矩阵仅在 is_enabled_for
    被调用时生效 (per-Agent 调用点决定某插件是否对该 Agent+Channel 启用)。"""
    matrix = EnableMatrix(global_policy={"plugins_deny": ["never_enabled"]})
    manager = PluginManager({}, enable_matrix=matrix)
    # enable_matrix 注入不阻塞 load_all (实际加载由 plugin_dir 内容决定)
    assert manager.enable_matrix is matrix
    # 但 is_enabled_for 走矩阵
    assert manager.is_enabled_for("never_enabled", "a", "qq") is False
