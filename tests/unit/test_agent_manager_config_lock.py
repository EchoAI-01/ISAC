"""Fix-2: AgentManager 按 agent_id 的配置锁, 修复并发 PATCH 丢更新的竞态。

_do_patch_agent() 原来的流程 (读 revision → 校验 if_match → 合并 → 持久化 →
reload_config) 中间有真正的 await 挂起点; 两个针对同一 agent_id 的并发 PATCH
如果都在对方完成前读到了同一份旧配置, 后完成的一个会用自己基于旧配置算出的
结果覆盖先完成的一个, 静默丢失一次更新即使两次请求都返回 200。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from isac.runtime.config import AgentConfig
from isac.runtime.manager import AgentManager


class _StubProviderManager:
    def for_agent(self, config: Any) -> None:
        return None


class _StubMemory:
    def __init__(self, namespace: str) -> None:
        self.namespace = namespace

    async def search(self, *args: Any, **kwargs: Any) -> list:
        return []

    async def store_episode(self, *args: Any, **kwargs: Any) -> str:
        return ""


def _make_manager() -> AgentManager:
    services = {
        "global_config": {},
        "provider_manager": _StubProviderManager(),
        "memory_factory": lambda namespace: _StubMemory(namespace),
    }
    return AgentManager(services)


def test_acquire_config_lock_returns_same_lock_for_same_agent_id() -> None:
    manager = _make_manager()
    lock_a = manager.acquire_config_lock("agent-1")
    lock_b = manager.acquire_config_lock("agent-1")
    assert lock_a is lock_b


def test_acquire_config_lock_returns_distinct_locks_for_distinct_agents() -> None:
    manager = _make_manager()
    lock_a = manager.acquire_config_lock("agent-1")
    lock_b = manager.acquire_config_lock("agent-2")
    assert lock_a is not lock_b


@pytest.mark.asyncio
async def test_concurrent_patches_to_same_agent_do_not_lose_updates(tmp_path) -> None:
    """两个并发 PATCH (改不同字段) 都必须生效, 不能因为竞态互相覆盖。"""
    from isac.control.api.routes_agents import _do_patch_agent

    manager = _make_manager()
    await manager.create(AgentConfig(agent_id="race-test", display_name="Before"))
    agents_dir_path = tmp_path / "agents"

    original_reload = manager.reload_config

    async def slow_reload(agent_id: str, config: AgentConfig) -> None:
        # 人为拉宽竞态窗口, 强制两个并发 PATCH 真正交错执行 (否则协程可能一次跑完,
        # 测试无法可靠复现竞态)。
        await asyncio.sleep(0.05)
        await original_reload(agent_id, config)

    manager.reload_config = slow_reload  # type: ignore[method-assign]

    async def patch_display_name() -> dict:
        return await _do_patch_agent(
            manager, "race-test", {"display_name": "A"}, None, None, agents_dir_path,
        )

    async def patch_trigger_words() -> dict:
        return await _do_patch_agent(
            manager, "race-test", {"trigger_words": ["hi"]}, None, None, agents_dir_path,
        )

    await asyncio.gather(patch_display_name(), patch_trigger_words())

    final_instance = await manager.get("race-test")
    assert final_instance is not None
    assert final_instance.config.display_name == "A"
    assert final_instance.config.trigger_words == ["hi"]
