"""U1 事件溯源会话内核全链路集成测试。

验收覆盖 (DEVELOPMENT_PLAN §四 U1):
- 入站消息即持久事件 ("Model-visible ⟺ Logged"): LLM 调用前 message.user 已落盘;
- 回复成功 → turn.completed 事件落盘;
- 滑动窗口历史开箱可用: 同群第二轮 LLM 能看到第一轮的问答;
- 隔天回到同一群聊仍保持上下文: store 重启 (模拟进程重启) 后历史窗口依旧派生;
- episodes 写入改事件投影: 记忆写入内容从事件流派生 (检索面不变);
- torn-tail: 孤儿 tool.called 在启动 repair 后补 OUTCOME_UNKNOWN。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from isac.channel.model import ISACMessage, MessageSegment
from isac.channel.registry import ChannelRegistry
from isac.gateway.event_bus import EventBus
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.main import _start_session_event_store, process_message
from isac.observability import get_default_metrics
from isac.provider.manager import ProviderManager
from isac.router.router import MessageRouter
from isac.router.types import RoutingRules
from isac.runtime.config import AgentConfig
from isac.runtime.manager import AgentManager
from isac.session.event_store import SessionEventStore
from isac.session.history import SessionHistoryDeriver
from isac.session.models import (
    EVENT_TOOL_CALLED,
    EVENT_TOOL_OUTCOME,
    EVENT_TURN_COMPLETED,
    EVENT_USER_MESSAGE,
    SessionEvent,
)
from tests.fixtures.fakes import FakeChannel, FakeLLMProvider, make_final_reply


class RecordingMemoryPipeline:
    """记录 store_episode 调用的记忆替身 (episodes 投影断言用)。"""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self.episodes: list[dict[str, Any]] = []

    async def search(self, query: str, top_k: int = 5, filters: dict | None = None, **kw: Any) -> list:
        return []

    async def store_episode(
        self,
        content: str,
        session_id: str,
        user_id: str = "",
        agent_id: str = "",
        group_id: str = "",
        metadata: dict | None = None,
    ) -> str:
        self.episodes.append(
            {"content": content, "session_id": session_id, "user_id": user_id, "group_id": group_id}
        )
        return f"ep-{len(self.episodes)}"

    async def get_context(self, *args: Any, **kwargs: Any) -> str:
        return ""

    async def close(self) -> None:
        return None


async def _build_u1_e2e(
    tmp_path: Path,
    *,
    store: SessionEventStore | None = None,
    memory_pipeline: RecordingMemoryPipeline | None = None,
) -> tuple[Any, ...]:
    """构造带 U1 事件溯源接线的 E2E 夹具。"""
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    provider = FakeLLMProvider()
    provider_manager.register(provider)

    session_mgr = SessionManager({})
    event_store = store or SessionEventStore(str(tmp_path / "session_events.db"))
    await event_store.start()
    pipeline = memory_pipeline or RecordingMemoryPipeline("default")

    services: dict[str, Any] = {
        "global_config": {"session": {"history": {"enabled": True, "window_turns": 5}}},
        "provider_manager": provider_manager,
        "memory_factory": lambda namespace: pipeline,
        "metrics": metrics,
        "session_mgr": session_mgr,
        "session_event_store": event_store,
        "session_history": SessionHistoryDeriver(window_turns=5),
    }
    agent_manager = AgentManager(services)
    await agent_manager.create(
        AgentConfig(agent_id="default", display_name="ISAC", trigger_words=[])
    )
    await agent_manager.start("default")

    router = MessageRouter(
        RoutingRules(bindings=[], default_agents={"fake": "default"}),
        agents_provider=agent_manager.routing_infos,
    )
    event_bus = EventBus()
    user_mapper = UserMapper()
    channel_registry = ChannelRegistry()
    channel = FakeChannel()
    channel_registry.register(channel)

    return (
        agent_manager, router, event_bus, session_mgr, user_mapper,
        channel_registry, channel, provider, event_store, pipeline, services,
    )


async def _run(message: ISACMessage, harness: tuple[Any, ...]) -> None:
    (am, router, eb, sm, um, cr, *_rest) = harness
    await process_message(
        message,
        event_bus=eb,
        router=router,
        session_mgr=sm,
        user_mapper=um,
        agent_manager=am,
        channel_registry=cr,
        metrics=get_default_metrics(),
    )


def _msg(content: str, *, user_id: str = "u1", group_id: str | None = "g1", msg_id: str = "m1") -> ISACMessage:
    segments = [MessageSegment(type="at", data={}), MessageSegment(type="text", data={"text": content})]
    return ISACMessage(
        msg_id=msg_id,
        platform="fake",
        timestamp=1,
        user_id=user_id,
        user_name=user_id,
        group_id=group_id,
        content=content,
        segments=segments,
    )


@pytest.mark.asyncio
async def test_inbound_message_logged_before_llm_and_turn_completed(tmp_path: Path) -> None:
    """Model-visible ⟺ Logged: LLM 调用前 message.user 已 durable; 回复后 turn.completed。"""
    harness = await _build_u1_e2e(tmp_path)
    (am, *_r, channel, provider, store, _pipe, _svcs) = harness

    # 包一层 chat, 在 LLM 真正被调用瞬间抓事件表状态 (验证"副作用前落盘")。
    events_at_llm_time: list[int] = []
    orig_chat = provider.chat

    async def spy_chat(system: str, messages: list[dict], tools: list[dict] | None = None, **kw: Any):
        events_at_llm_time.append(await store.max_seq("default:fake:group:g1"))
        return await orig_chat(system, messages, tools, **kw)

    provider.chat = spy_chat  # type: ignore[method-assign]
    provider.queue_reply(make_final_reply("你好呀"))

    await _run(_msg("大家好", msg_id="m1"), harness)
    await am.drain_background_tasks(timeout_seconds=2.0)

    assert len(channel.replies) == 1
    assert events_at_llm_time and events_at_llm_time[0] >= 1  # LLM 前用户消息已落事件
    events = await store.fetch("default:fake:group:g1")
    types = [e.event_type for e in events]
    assert EVENT_USER_MESSAGE in types
    assert EVENT_TURN_COMPLETED in types
    turn_ev = next(e for e in events if e.event_type == EVENT_TURN_COMPLETED)
    assert turn_ev.payload["content"] == "你好呀"
    await store.stop()


@pytest.mark.asyncio
async def test_second_turn_sees_history_window(tmp_path: Path) -> None:
    """滑动窗口开箱可用: 同群第二轮 LLM messages 含第一轮问答。"""
    harness = await _build_u1_e2e(tmp_path)
    (am, *_r, channel, provider, store, _pipe, _svcs) = harness

    provider.queue_reply(make_final_reply("第一轮回复"))
    await _run(_msg("第一句话", msg_id="m1"), harness)
    await am.drain_background_tasks(timeout_seconds=2.0)

    provider.queue_reply(make_final_reply("第二轮回复"))
    await _run(_msg("第二句话", msg_id="m2"), harness)
    await am.drain_background_tasks(timeout_seconds=2.0)

    assert len(channel.replies) == 2
    second_call = provider.calls[-1]["messages"]
    joined = "\n".join(str(m.get("content", "")) for m in second_call)
    assert "第一句话" in joined  # 历史窗口包含上一轮用户输入
    assert "第一轮回复" in joined  # 与上一轮助手输出
    assert second_call[-1]["content"] == "第二句话"  # 当前 burst 仍是最后一条
    await store.stop()


@pytest.mark.asyncio
async def test_restart_same_group_keeps_context_next_day(tmp_path: Path) -> None:
    """隔天回到同一群聊仍保持上下文: store 关闭重开 (模拟重启) 后窗口派生不断档。"""
    db_path = str(tmp_path / "session_events.db")
    harness = await _build_u1_e2e(tmp_path)
    (am, *_r, channel, provider, store, _pipe, services) = harness

    provider.queue_reply(make_final_reply("昨天聊过了"))
    await _run(_msg("昨天的话题", msg_id="m1"), harness)
    await am.drain_background_tasks(timeout_seconds=2.0)
    await store.stop()  # 模拟进程退出

    # "隔天" 重启: 新 store 打开同一事件库, 走生产启动路径 (建表 + torn-tail 修复)。
    store2 = SessionEventStore(db_path)
    await _start_session_event_store(store2)
    services["session_event_store"] = store2

    provider.queue_reply(make_final_reply("今天继续"))
    await _run(_msg("今天接着聊", msg_id="m2"), harness)
    await am.drain_background_tasks(timeout_seconds=2.0)

    assert len(channel.replies) == 2
    joined = "\n".join(str(m.get("content", "")) for m in provider.calls[-1]["messages"])
    assert "昨天的话题" in joined  # 重启后历史窗口仍在
    assert "昨天聊过了" in joined
    assert provider.calls[-1]["messages"][-1]["content"] == "今天接着聊"
    await store2.stop()


@pytest.mark.asyncio
async def test_episodes_written_as_event_projection(tmp_path: Path) -> None:
    """episodes 写入改事件投影: 记忆内容来自事件流 (用户输入 + 回复都在)。"""
    pipeline = RecordingMemoryPipeline("default")
    harness = await _build_u1_e2e(tmp_path, memory_pipeline=pipeline)
    (am, *_r, channel, provider, store, _pipe, _svcs) = harness

    provider.queue_reply(make_final_reply("投影回复"))
    await _run(_msg("投影测试", msg_id="m1"), harness)
    await am.drain_background_tasks(timeout_seconds=2.0)

    assert len(pipeline.episodes) == 1
    content = pipeline.episodes[0]["content"]
    assert "投影测试" in content
    assert "投影回复" in content
    # 事件流与 episodes 同源: 事件里能逐字找到 episodes 的双方内容
    events = await store.fetch("default:fake:group:g1")
    user_ev = next(e for e in events if e.event_type == EVENT_USER_MESSAGE)
    turn_ev = next(e for e in events if e.event_type == EVENT_TURN_COMPLETED)
    assert user_ev.payload["content"] in content
    assert turn_ev.payload["content"] in content
    await store.stop()


@pytest.mark.asyncio
async def test_history_disabled_zero_behavior(tmp_path: Path) -> None:
    """session.history.enabled=false: 回退旧行为, LLM 只看当前 burst, 无事件落盘。"""
    harness = await _build_u1_e2e(tmp_path)
    (am, *_r, channel, provider, store, _pipe, services) = harness
    services["global_config"] = {"session": {"history": {"enabled": False}}}

    provider.queue_reply(make_final_reply("回复A"))
    await _run(_msg("第一句", msg_id="m1"), harness)
    await am.drain_background_tasks(timeout_seconds=2.0)
    provider.queue_reply(make_final_reply("回复B"))
    await _run(_msg("第二句", msg_id="m2"), harness)
    await am.drain_background_tasks(timeout_seconds=2.0)

    # 第二轮 LLM messages 只有当前 burst (无历史窗口)
    assert provider.calls[-1]["messages"][-1]["content"] == "第二句"
    joined = "\n".join(str(m.get("content", "")) for m in provider.calls[-1]["messages"])
    assert "第一句" not in joined
    assert await store.max_seq("default:fake:group:g1") == 0  # 关闭时不落事件
    await store.stop()


@pytest.mark.asyncio
async def test_torn_tail_repair_on_startup(tmp_path: Path) -> None:
    """kill -9 容忍: 孤儿 tool.called 启动 repair 后补 OUTCOME_UNKNOWN, 重放不崩。"""
    db_path = str(tmp_path / "session_events.db")
    store = SessionEventStore(db_path)
    await store.start()
    key = "default:fake:group:g1"
    await store.append(
        SessionEvent(session_key=key, event_type=EVENT_USER_MESSAGE, timestamp=1, payload={"content": "跑个命令"})
    )
    await store.append(
        SessionEvent(session_key=key, event_type=EVENT_TOOL_CALLED, timestamp=1, payload={"tool_name": "bash"})
    )
    await store.flush()
    # 不调 stop() 的 flush 收尾, 直接弃用连接模拟崩溃前已 commit 的状态
    await store._db.close()  # type: ignore[union-attr]

    # 生产启动路径: 逐分区 torn-tail 修复
    store2 = SessionEventStore(db_path)
    await _start_session_event_store(store2)
    events = await store2.fetch(key)
    outcomes = [e for e in events if e.event_type == EVENT_TOOL_OUTCOME]
    assert len(outcomes) == 1
    assert outcomes[0].payload["outcome"] == "OUTCOME_UNKNOWN"
    # 修复后窗口派生不崩 (tool 事件不进聊天历史)
    msgs = SessionHistoryDeriver().derive_window(events)
    assert msgs == [{"role": "user", "content": "跑个命令"}]
    await store2.stop()
