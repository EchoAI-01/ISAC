"""U2 ServiceContainer: services 袋类型化 (dict 子类, 核心键属性访问)。

背景 (架构债 Z2): build_services 返回裸 dict, 下游 200+ 处防御式 ``services.get(...)``
字符串键 —— 键错配只能在运行时发现。U2 第一步: dict 子类 + 核心键**类型化属性**,
装配层 (wiring/bootstrap/dispatch) 经属性访问, 键错配在类型层不可能 (mypy strict);
仍是 dict 子类, 全部既有 ``services["x"]`` / ``services.get`` / ``{**services}``
调用方零改动 (渐进迁移, 剩余字符串键访问 U9 批清)。

属性只在对应键已注册后可用 (build_services/bootstrap 接线顺序之后); 早于接线
访问抛 KeyError —— 与裸 dict 同语义, 不吞错。
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
    """共享服务容器 (dict 子类 + 核心键类型化属性)。

    核心键 (build_services 注册): global_config / metrics / provider_manager /
    model_catalog / model_router / artifact_store / uploads_store / usage_recorder /
    session_event_store / media_normalizer; 启动键 (bootstrap 注册):
    channel_registry / session_mgr / session_lock / session_write_gate / bus。
    """

    # ── build_services 注册的核心键 ──────────────────────────

    @property
    def global_config(self) -> dict[str, Any]:
        return self["global_config"]

    @property
    def metrics(self) -> MetricsCollector:
        return self["metrics"]

    @property
    def provider_manager(self) -> ProviderManager:
        return self["provider_manager"]

    @property
    def model_catalog(self) -> ModelCatalog:
        return self["model_catalog"]

    @property
    def model_router(self) -> ModelRouter:
        return self["model_router"]

    @property
    def artifact_store(self) -> Any:
        return self["artifact_store"]

    @property
    def uploads_store(self) -> Any:
        return self["uploads_store"]

    @property
    def usage_recorder(self) -> Any:
        return self.get("usage_recorder")

    @property
    def session_event_store(self) -> Any:
        return self.get("session_event_store")

    @property
    def media_normalizer(self) -> Any:
        return self.get("media_normalizer")

    # ── bootstrap 注册的启动键 ───────────────────────────────

    @property
    def channel_registry(self) -> ChannelRegistry:
        return self["channel_registry"]

    @property
    def session_mgr(self) -> SessionManager:
        return self["session_mgr"]

    @property
    def session_lock(self) -> SessionLockManager:
        return self["session_lock"]

    @property
    def session_write_gate(self) -> SessionWriteGate:
        return self["session_write_gate"]

    @property
    def bus(self) -> Any:
        return self.get("bus")
