"""N5/Z1-A ServiceContainer 强类型迁移测试。

覆盖:
- 全注册键宽容属性: 键缺失返回 None (与迁移前防御式取值同语义), 注册后返回实例。
- dict 子类兼容: 下标读写 / in / 解包仍可用 (渐进迁移期既有调用方零改动)。
- AgentManager 归一化: 生产容器直通 (同一对象, bootstrap 后注册键可见);
  测试裸 dict 拷贝为容器 (属性访问可用)。
"""

from __future__ import annotations

import pytest

from isac.runtime.manager import AgentManager
from isac.runtime.services import ServiceContainer

# 与 scripts/check_redlines.py services_key_count 同一键集合 (build_services
# 字面量键 ∪ bootstrap 注册键); 新增注册键必须同步补属性, 此表兜底提醒。
_REGISTERED_KEYS = {
    "approval_gate", "artifact_store", "bash_allowlist", "bus", "channel_registry",
    "deny_guard", "global_config", "graph_store", "identity_resolver", "mcp_servers",
    "media_normalizer", "memory_factory", "metadata_store", "metrics", "model_catalog",
    "model_router", "provider_manager", "router", "session_event_store",
    "session_history", "session_lock", "session_mgr", "session_write_gate",
    "sparse_indexes", "storage_start", "subagent_journal", "subagent_supervisor",
    "tenant_context", "tenant_guard", "tenant_manager", "uploads_store",
    "usage_recorder", "usage_store", "vector_resolver", "vector_stores",
    "workspace_root",
}


def test_every_registered_key_has_tolerant_property() -> None:
    """每个注册键都有对应宽容属性: 空容器取键返回 None 不抛异常。"""
    container = ServiceContainer()
    for key in sorted(_REGISTERED_KEYS):
        assert getattr(container, key) is None, f"属性 {key} 缺失或非宽容"


# assembly 合并进 instance.services 的 per-Agent 键 (与 _AGENT_KEYS 一致)。
_PER_AGENT_KEYS = {
    "memory", "agent_id", "conversation_enabled", "conversation_registry",
    "conversation_state_store", "mcp_clients", "memory_consolidator",
    "mesh_action_broker", "proactive_scheduler", "progress_reporter_factory",
    "plugin_tools", "plugin_commands", "plugin_agent_hooks", "plugin_prompt_builder",
}


def test_per_agent_keys_tolerant_and_readable() -> None:
    """per-Agent 键: 空容器宽容返回 None; instance.services 合并面属性可读。"""
    container = ServiceContainer()
    for key in sorted(_PER_AGENT_KEYS):
        assert getattr(container, key) is None
    merged = ServiceContainer({**container, "memory": "mem", "agent_id": "a1"})
    assert merged.memory == "mem"
    assert merged.agent_id == "a1"
    assert merged.mcp_clients is None  # 未写入的 per-Agent 键仍宽容


def test_property_returns_registered_value() -> None:
    sentinel = object()
    container = ServiceContainer({"global_config": {"a": 1}, "bus": sentinel})
    assert container.global_config == {"a": 1}
    assert container.bus is sentinel
    assert container.metrics is None  # 未注册键仍 None


def test_dict_semantics_preserved() -> None:
    """dict 子类兼容: 下标读写 / get / in / 解包不变 (渐进迁移期零破坏)。"""
    container = ServiceContainer({"metrics": "m"})
    container["bus"] = "b"
    assert container["bus"] == "b"
    assert container.get("metrics") == "m"
    assert "bus" in container
    assert {**container} == {"metrics": "m", "bus": "b"}


def test_agent_manager_passes_container_through_without_copy() -> None:
    """生产路径: build_services 返回容器 → 直通持有同一对象。

    bootstrap 先构造 AgentManager 再向同一容器注册 bus/router/session_* 等键,
    拷贝会让管理器永远看不到后注册的键 —— 同一性是硬约束。
    """
    container = ServiceContainer({"global_config": {}})
    manager = AgentManager(container)
    assert manager._services is container  # noqa: SLF001
    # 构造后注册的键立即可见
    container["bus"] = "late-bus"
    assert manager._services.bus == "late-bus"  # noqa: SLF001


def test_agent_manager_normalizes_bare_dict() -> None:
    """测试夹具路径: 裸 dict 拷贝为容器, 属性访问可用, 值不共享后续变更。"""
    manager = AgentManager({"global_config": {"conversation": {"enabled": False}}})
    assert isinstance(manager._services, ServiceContainer)  # noqa: SLF001
    assert manager._services.global_config == {"conversation": {"enabled": False}}  # noqa: SLF001
    assert manager._services.bus is None  # noqa: SLF001


def test_agent_manager_preserves_get_semantics_for_missing_keys() -> None:
    """迁移不变量: 缺键宽容 (None), 不抛 KeyError —— 与迁移前 get 语义一致。"""
    manager: AgentManager = AgentManager({"session_lock": None})
    assert manager._services.session_write_gate is None  # noqa: SLF001
    assert manager._services.metrics is None  # noqa: SLF001
    # _conversation_enabled 依赖宽容读取, 缺 global_config 也不炸
    empty = AgentManager({})
    assert empty._conversation_enabled() is False  # noqa: SLF001


@pytest.mark.parametrize("key", sorted(_REGISTERED_KEYS))
def test_property_names_match_keys(key: str) -> None:
    """属性名与键名一一对应 (防止属性名漂移导致取错键)。"""
    sentinel = object()
    container = ServiceContainer({key: sentinel})
    assert getattr(container, key) is sentinel
