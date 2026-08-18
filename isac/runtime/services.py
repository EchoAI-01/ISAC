"""U2 ServiceContainer: services 袋类型化 (dict 子类, 全键类型化属性)。

背景 (架构债 Z1): build_services 返回裸 dict, 下游 200+ 处防御式字符串键取值,
键错配只能在运行时发现。U2 第一步落地 dict 子类 + 核心键类型化属性 (装配层经
属性访问); N5/Z1-A 补齐全部注册键并统一为**宽容属性** (键缺失返回 None, 与
既有防御式取值语义一致 —— 测试夹具常以部分字典构造 AgentManager, 严格下标会
把 None 语义变成 KeyError)。仍是 dict 子类, 全部既有字符串键调用方零改动
(渐进迁移, 残余字符串键访问由 U9 红线棘轮只减不增地批清)。

装配层不变量 (build_services/bootstrap 恒注册的键) 由消费侧按需 cast/assert,
容器本体不假设注册时序 —— 早于接线取键得到 None, 与裸 dict 的 get 同语义。
"""

from __future__ import annotations

from typing import Any

from isac.channel.registry import ChannelRegistry
from isac.gateway.lock import SessionLockManager
from isac.gateway.session import SessionManager
from isac.observability import MetricsCollector
from isac.provider.catalog import ModelCatalog
from isac.provider.manager import ProviderManager
from isac.provider.router import ModelRouter
from isac.runtime.write_gate import SessionWriteGate


class ServiceContainer(dict):
    """共享服务容器 (dict 子类 + 全注册键类型化宽容属性)。

    键全集 = build_services 字面量键 ∪ bootstrap 注册键 (scripts/check_redlines.py
    的 services_key_count 棘轮盯同一集合)。属性全部宽容: 键缺失返回 None,
    调用方沿用既有 None 防御, 行为与迁移前的 get 取值完全一致。
    """

    # ── build_services 注册键 ────────────────────────────────

    @property
    def global_config(self) -> dict[str, Any] | None:
        return self.get("global_config")

    @property
    def metrics(self) -> MetricsCollector | None:
        return self.get("metrics")

    @property
    def provider_manager(self) -> ProviderManager | None:
        return self.get("provider_manager")

    @property
    def model_catalog(self) -> ModelCatalog | None:
        return self.get("model_catalog")

    @property
    def model_router(self) -> ModelRouter | None:
        return self.get("model_router")

    @property
    def artifact_store(self) -> Any:
        return self.get("artifact_store")

    @property
    def uploads_store(self) -> Any:
        return self.get("uploads_store")

    @property
    def usage_recorder(self) -> Any:
        return self.get("usage_recorder")

    @property
    def usage_store(self) -> Any:
        return self.get("usage_store")

    @property
    def session_event_store(self) -> Any:
        return self.get("session_event_store")

    @property
    def media_normalizer(self) -> Any:
        return self.get("media_normalizer")

    @property
    def memory_factory(self) -> Any:
        return self.get("memory_factory")

    @property
    def metadata_store(self) -> Any:
        return self.get("metadata_store")

    @property
    def graph_store(self) -> Any:
        return self.get("graph_store")

    @property
    def sparse_indexes(self) -> Any:
        return self.get("sparse_indexes")

    @property
    def vector_resolver(self) -> Any:
        return self.get("vector_resolver")

    @property
    def vector_stores(self) -> Any:
        return self.get("vector_stores")

    @property
    def storage_start(self) -> Any:
        return self.get("storage_start")

    @property
    def tenant_guard(self) -> Any:
        return self.get("tenant_guard")

    @property
    def tenant_context(self) -> Any:
        return self.get("tenant_context")

    @property
    def tenant_manager(self) -> Any:
        return self.get("tenant_manager")

    @property
    def subagent_supervisor(self) -> Any:
        return self.get("subagent_supervisor")

    @property
    def subagent_journal(self) -> Any:
        return self.get("subagent_journal")

    @property
    def workspace_root(self) -> Any:
        return self.get("workspace_root")

    @property
    def bash_allowlist(self) -> Any:
        return self.get("bash_allowlist")

    # ── bootstrap 注册的启动键 ───────────────────────────────

    @property
    def channel_registry(self) -> ChannelRegistry | None:
        return self.get("channel_registry")

    @property
    def session_mgr(self) -> SessionManager | None:
        return self.get("session_mgr")

    @property
    def session_lock(self) -> SessionLockManager | None:
        return self.get("session_lock")

    @property
    def session_write_gate(self) -> SessionWriteGate | None:
        return self.get("session_write_gate")

    @property
    def session_history(self) -> Any:
        return self.get("session_history")

    @property
    def bus(self) -> Any:
        return self.get("bus")

    @property
    def router(self) -> Any:
        return self.get("router")

    @property
    def identity_resolver(self) -> Any:
        return self.get("identity_resolver")

    @property
    def approval_gate(self) -> Any:
        return self.get("approval_gate")

    @property
    def deny_guard(self) -> Any:
        return self.get("deny_guard")

    @property
    def mcp_servers(self) -> Any:
        return self.get("mcp_servers")

    # ── per-Agent 键 (assembly 合并进 instance.services) ─────
    # instance.services = 全局容器快照 ∪ 下列键; 属性集覆盖两面, 同一实例经
    # 属性访问两面的键都成立 (全局键在 per-Agent 袋上是合并快照)。

    @property
    def memory(self) -> Any:
        return self.get("memory")

    @property
    def agent_id(self) -> Any:
        return self.get("agent_id")

    @property
    def conversation_enabled(self) -> Any:
        return self.get("conversation_enabled")

    @property
    def conversation_registry(self) -> Any:
        return self.get("conversation_registry")

    @property
    def conversation_state_store(self) -> Any:
        return self.get("conversation_state_store")

    @property
    def mcp_clients(self) -> Any:
        return self.get("mcp_clients")

    @property
    def memory_consolidator(self) -> Any:
        return self.get("memory_consolidator")

    @property
    def mesh_action_broker(self) -> Any:
        return self.get("mesh_action_broker")

    @property
    def proactive_scheduler(self) -> Any:
        return self.get("proactive_scheduler")

    @property
    def progress_reporter_factory(self) -> Any:
        return self.get("progress_reporter_factory")

    @property
    def plugin_tools(self) -> Any:
        return self.get("plugin_tools")

    @property
    def plugin_commands(self) -> Any:
        return self.get("plugin_commands")

    @property
    def plugin_agent_hooks(self) -> Any:
        return self.get("plugin_agent_hooks")

    @property
    def plugin_prompt_builder(self) -> Any:
        return self.get("plugin_prompt_builder")
