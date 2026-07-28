"""MemoryConsolidator 骨架单测 (S2, TODO(consolidator))。

验证后台整合器骨架: run_once 为 no-op 返回全零 ConsolidationResult (零读写);
start/stop 后台循环可重复调用且安全取消; assembly._build_memory_consolidator
默认关闭 (未配置/NoOp 记忆时返回 None), 显式 enabled 时按记忆命名空间构造。
骨架阶段主链路零行为变化。
"""

from __future__ import annotations

import asyncio

import pytest

from isac.memory.consolidator import ConsolidationResult, MemoryConsolidator
from isac.runtime.assembly import _build_memory_consolidator
from isac.runtime.config import AgentConfig


class _FakePipeline:
    """带 metadata/namespace 的假记忆流水线 (触发构造分支)。"""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self.metadata = object()


class _NoOpPipeline:
    """无 metadata 的空流水线 (NoOpMemoryPipeline 语义)。"""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace


@pytest.mark.asyncio
async def test_run_once_is_noop_zero_result() -> None:
    consolidator = MemoryConsolidator(agent_id="a1", namespace="a1")
    result = await consolidator.run_once()
    assert isinstance(result, ConsolidationResult)
    assert (result.merged_episodes, result.pruned_episodes, result.updated_profiles) == (0, 0, 0)


@pytest.mark.asyncio
async def test_start_stop_idempotent() -> None:
    consolidator = MemoryConsolidator(agent_id="a1", namespace="a1", interval_seconds=1.0)
    await consolidator.start()
    await consolidator.start()  # 重复 start 不重启, 不抛异常
    await consolidator.stop()
    await consolidator.stop()  # 重复 stop 安全


@pytest.mark.asyncio
async def test_loop_runs_run_once_and_isolates_exception() -> None:
    """后台循环按 interval 调用 run_once; 单次异常被隔离不终止循环。"""
    calls = {"n": 0}

    class _Boomer(MemoryConsolidator):
        async def run_once(self) -> ConsolidationResult:  # type: ignore[override]
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return ConsolidationResult()

    consolidator = _Boomer(agent_id="a1", namespace="a1")
    consolidator._interval_seconds = 0.01  # noqa: SLF001  绕过 1.0s 生产下限, 加速循环驱动
    await consolidator.start()
    await asyncio.sleep(0.05)  # 足够触发多次 run_once
    await consolidator.stop()
    assert calls["n"] >= 2  # 第一次抛异常后循环仍继续


def test_build_consolidator_default_off() -> None:
    """未配置 memory.consolidation → None (零行为变化)。"""
    config = AgentConfig(agent_id="a1")
    assert _build_memory_consolidator(config, {}, _FakePipeline("a1")) is None


def test_build_consolidator_noop_pipeline_returns_none() -> None:
    """启用但记忆是 NoOp (无 metadata) → 不构造。"""
    config = AgentConfig(agent_id="a1")
    global_config = {"memory": {"consolidation": {"enabled": True}}}
    assert _build_memory_consolidator(config, global_config, _NoOpPipeline("a1")) is None


def test_build_consolidator_enabled_with_metadata() -> None:
    config = AgentConfig(agent_id="a1")
    global_config = {"memory": {"consolidation": {"enabled": True, "interval_seconds": 120}}}
    consolidator = _build_memory_consolidator(config, global_config, _FakePipeline("ns-a1"))
    assert isinstance(consolidator, MemoryConsolidator)
