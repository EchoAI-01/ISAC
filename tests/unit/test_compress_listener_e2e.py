"""R7-⑥ COMPRESS hook listener 端到端测试 (经 hooks.fire 真实调用链)。

区别于 test_memory_consolidator_r4.py 的纯单元测试 (直调 enqueue_compression/run_once),
本文件经 ``AgentHooks.fire(AgentHookPoint.COMPRESS, ...)`` 真实触发 assembly 注册的
``_on_compress`` listener 闭包, 验证生产 hook 调用链: fire → listener → 入队 → run_once
摘要落盘。满足 MODULE_GUIDE §二"第三道坎": 经真实触发者 (fire) 驱动而非直调。
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from isac.agent.hooks import AgentHooks
from isac.core.events import AgentHookPoint
from isac.core.types import LLMResponse
from isac.gateway.models import Session
from isac.memory.consolidator import MemoryConsolidator
from isac.memory.storage.metadata import MetadataStore
from isac.runtime.assembly import _register_compress_listener  # noqa: PLC2701

NAMESPACE = "agent_compress"


class _ScriptedLLM:
    """按调用顺序返回预设响应的假 LLM (记录所有调用)。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(
        self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs: Any
    ) -> LLMResponse:
        self.calls.append({"system": system, "messages": messages, "kwargs": kwargs})
        text = self._responses.pop(0) if self._responses else ""
        return LLMResponse(content=text)


@pytest.fixture
async def store(tmp_path: Path) -> AsyncGenerator[MetadataStore, None]:
    s = MetadataStore(str(tmp_path / "memory.db"))
    await s.init_schema()
    yield s


@pytest.mark.asyncio
async def test_compress_listener_fires_via_hook_and_enqueues(store: MetadataStore) -> None:
    """经 hooks.fire(COMPRESS) 触发 assembly 注册的 _on_compress listener → 入队。

    验证生产 hook 调用链真实生效 (非直调 enqueue_compression): fire 经 AgentHooks
    按优先级调 _on_compress, 从 context.session 取 session_id, 把 messages 快照入队。
    """
    consolidator = MemoryConsolidator(agent_id=NAMESPACE, namespace=NAMESPACE, metadata=store, llm=_ScriptedLLM([]))
    hooks = AgentHooks()
    _register_compress_listener(hooks, consolidator)
    # 构造经 fire 传入的 context (含 session.session_id, 仿生产 AgentContext)
    context = SimpleNamespace(session=Session(
        session_id="sess-fire", user_id="u1", agent_id=NAMESPACE, platform="web",
    ))
    messages = [{"role": "user", "content": "讨论了部署方案"}, {"role": "assistant", "content": "好的"}]
    # 真实触发: 经 hooks.fire 调 listener (非直调 enqueue_compression)
    await hooks.fire(AgentHookPoint.COMPRESS, messages, context)
    # listener 入队成功
    assert len(consolidator._compress_queue) == 1  # noqa: SLF001
    assert consolidator._compress_queue[0]["session_id"] == "sess-fire"  # noqa: SLF001
    assert consolidator._compress_queue[0]["messages"] == messages  # noqa: SLF001


@pytest.mark.asyncio
async def test_compress_listener_skips_when_no_session(store: MetadataStore) -> None:
    """context.session 缺失或 session_id 空 → listener 早退不入队 (不抛)。"""
    consolidator = MemoryConsolidator(agent_id=NAMESPACE, namespace=NAMESPACE, metadata=store, llm=_ScriptedLLM([]))
    hooks = AgentHooks()
    _register_compress_listener(hooks, consolidator)
    # 无 session 的 context
    await hooks.fire(AgentHookPoint.COMPRESS, [{"role": "user", "content": "x"}], SimpleNamespace())
    assert consolidator._compress_queue == []  # noqa: SLF001


@pytest.mark.asyncio
async def test_compress_fire_then_run_once_persists_summary(store: MetadataStore) -> None:
    """端到端闭环: fire(COMPRESS) 入队 → run_once 摘要 → episodes.summary 落盘。

    先落盘一条 episode 供 latest_episode_id_for_session 命中; user_id 留空避免
    画像归纳步骤抢占 scripted LLM 响应 (本测试聚焦 compress 链路)。
    """
    await store.store_episode(NAMESPACE, {
        "id": "ep1", "session_id": "sess-fire", "user_id": "", "content": "原始会话内容",
    })
    llm = _ScriptedLLM(responses=["这是会话的关键压缩摘要。"])
    consolidator = MemoryConsolidator(agent_id=NAMESPACE, namespace=NAMESPACE, metadata=store, llm=llm)
    hooks = AgentHooks()
    _register_compress_listener(hooks, consolidator)
    context = SimpleNamespace(session=Session(
        session_id="sess-fire", user_id="u1", agent_id=NAMESPACE, platform="web",
    ))
    # 1. fire 触发入队 (不调 LLM)
    await hooks.fire(AgentHookPoint.COMPRESS, [{"role": "user", "content": "讨论部署"}], context)
    assert llm.calls == []  # 入队阶段不调 LLM (守护 hook 禁直接调 LLM 规范)
    # 2. run_once 消费队列 → LLM 摘要 → 落盘
    result = await consolidator.run_once()
    assert result.compressed_summaries == 1
    assert len(llm.calls) == 1  # 摘要调了一次 LLM
    # 3. summary 落 episodes.summary 列
    ep_id = await store.latest_episode_id_for_session(NAMESPACE, "sess-fire")
    assert ep_id == "ep1"
    summary = await store.get_episode_summary(NAMESPACE, ep_id)
    assert summary == "这是会话的关键压缩摘要。"


# 占位: 避免 asyncio/tempfile 未使用 import 警告 (保留供后续扩展)
_ = asyncio
_ = tempfile
