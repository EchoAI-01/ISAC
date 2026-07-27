"""P1: 拟人化激活集成测试 (DEVELOPMENT_PLAN.md §四 P1)。

conversation.enabled=true 时端到端验收:
- debounce: 静默窗口内连续消息合并为一轮处理 (一次 LLM 调用, 合并输入)
- wait 唤醒: WAITING 会话收到新消息, wait 工具以 MESSAGE 原因被唤醒
- 打断: thinking 期间新消息 request_interrupt → 旧回复被抑制 + 下一轮注入提示
- 主动任务: ProactiveScheduler 唤醒 → 强制话轮 → 回复发回原 Channel
- 恢复: 会话快照落盘 → 重组装 Agent → RecoveryInjector 注入"刚醒来"提示
enabled=false (默认) 时零行为变化 (既有集成测试兜底)。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from isac.channel.model import MessageSegment
from isac.channel.registry import ChannelRegistry
from isac.core.types import LLMResponse
from isac.gateway.event_bus import EventBus
from isac.gateway.lock import SessionLockManager
from isac.gateway.session import SessionManager
from isac.gateway.user_mapper import UserMapper
from isac.main import make_message_dispatcher
from isac.memory.pipeline import NoOpMemoryPipeline
from isac.observability import get_default_metrics
from isac.provider.manager import ProviderManager
from isac.router.router import MessageRouter
from isac.router.types import RoutingRules
from isac.runtime.config import AgentConfig
from isac.runtime.conversation import ProactiveTask
from isac.runtime.manager import AgentManager
from tests.fixtures.fakes import FakeChannel, FakeLLMProvider, make_final_reply


class SlowFakeProvider(FakeLLMProvider):
    """带延迟的 Fake Provider (制造 thinking 时间窗供打断)。"""

    def __init__(self, *, delay: float = 0.0, scripted_replies: list[LLMResponse] | None = None) -> None:
        super().__init__(scripted_replies=scripted_replies)
        self._delay = delay

    async def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs: Any):
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        return await super().chat(system, messages, tools, **kwargs)


async def _build_env(
    provider: FakeLLMProvider,
    *,
    conversation: dict[str, Any] | None = None,
):
    """conversation.enabled=true 的完整 E2E 夹具 (dispatcher + manager + FakeChannel)。"""
    metrics = get_default_metrics()
    provider_manager = ProviderManager({}, metrics=metrics)
    provider_manager.register(provider)
    conv_config = {"enabled": True, "debounce_seconds": 0.0, **(conversation or {})}
    global_config: dict[str, Any] = {"conversation": conv_config}

    session_mgr = SessionManager({})
    session_lock = SessionLockManager()
    channel_registry = ChannelRegistry()
    fake_channel = FakeChannel()
    channel_registry.register(fake_channel)

    services: dict[str, Any] = {
        "global_config": global_config,
        "provider_manager": provider_manager,
        "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
        "metrics": metrics,
        "session_mgr": session_mgr,
        "session_lock": session_lock,
        "channel_registry": channel_registry,
    }
    agent_manager = AgentManager(services)
    await agent_manager.create(AgentConfig(agent_id="a", display_name="A"))
    await agent_manager.start("a")

    router = MessageRouter(
        RoutingRules(default_agents={"fake": "a"}), agents_provider=agent_manager.routing_infos
    )
    handle_message, drain_inflight = make_message_dispatcher(
        event_bus=EventBus(),
        router=router,
        session_mgr=session_mgr,
        user_mapper=UserMapper(),
        agent_manager=agent_manager,
        channel_registry=channel_registry,
        metrics=metrics,
        session_lock=session_lock,
        drain_timeout_seconds=15.0,
    )
    fake_channel.on_message = handle_message
    return agent_manager, fake_channel, drain_inflight, session_mgr


async def _inject(channel: FakeChannel, content: str, *, user_id: str = "alice") -> None:
    await channel.receive_inject(
        content,
        user_id=user_id,
        segments=[
            MessageSegment(type="at", data={}),
            MessageSegment(type="text", data={"text": content}),
        ],
    )


async def _drain_all(am: AgentManager, drain) -> None:
    await drain()
    pending = list(am._memory_tasks)  # noqa: SLF001
    if pending:
        await asyncio.gather(*pending)


@pytest.mark.asyncio
async def test_debounce_merges_consecutive_messages() -> None:
    """静默窗口内连续两条消息合并为一次 LLM 调用, 输入含两条消息文本。"""
    provider = SlowFakeProvider(scripted_replies=[make_final_reply("合并回复")])
    am, channel, drain, _ = await _build_env(provider, conversation={"debounce_seconds": 0.3})

    await _inject(channel, "先说前半句")
    await asyncio.sleep(0.05)  # 静默窗口内的第二条
    await _inject(channel, "接着补后半句")
    await _drain_all(am, drain)

    # 第一条在 debounce 后发现有更新消息 → 弃权; 第二条合并处理 → 只有一次 LLM 调用
    assert len(provider.calls) == 1
    merged_input = provider.calls[0]["messages"][-1]["content"]
    assert "先说前半句" in merged_input and "接着补后半句" in merged_input
    assert [r.content for r in channel.replies] == ["合并回复"]


@pytest.mark.asyncio
async def test_interrupt_supersedes_old_reply() -> None:
    """thinking 期间新消息打断: 旧回复被抑制, 新一轮注入"被打断"提示。"""
    provider = SlowFakeProvider(
        delay=0.3,
        scripted_replies=[make_final_reply("被打断的旧回复"), make_final_reply("基于新消息的回复")],
    )
    am, channel, drain, _ = await _build_env(provider)

    await _inject(channel, "第一个问题")
    await asyncio.sleep(0.1)  # 第一轮已进入 thinking (LLM delay 0.3s)
    await _inject(channel, "等等我改主意了")  # 锁外信号: request_interrupt
    await _drain_all(am, drain)

    # 旧回复被抑制, 只有第二轮的回复送达
    contents = [r.content for r in channel.replies]
    assert "被打断的旧回复" not in contents
    assert "基于新消息的回复" in contents
    # 第二轮 System Prompt 注入了"被打断"内部参考
    assert any("被新消息打断" in (c["system"] or "") for c in provider.calls[1:])


@pytest.mark.asyncio
async def test_proactive_task_triggers_forced_turn() -> None:
    """主动任务: 入队 → 调度唤醒 → 强制话轮 → 回复发回原 Channel。"""
    provider = SlowFakeProvider(
        scripted_replies=[make_final_reply("你好呀"), make_final_reply("主动找你聊聊")]
    )
    am, channel, drain, session_mgr = await _build_env(
        provider,
        conversation={"proactive": {"min_interval_seconds": 0, "poll_interval_seconds": 0.05}},
    )

    # 先聊一句建立会话 (主动任务需要既有会话上下文)
    await _inject(channel, "在吗")
    await _drain_all(am, drain)
    sessions = await session_mgr.list_sessions(agent_id="a")
    assert sessions
    session_id = sessions[0].session_id

    instance = await am.get("a")
    scheduler = instance.services["proactive_scheduler"]
    scheduler.queue.enqueue(
        ProactiveTask(
            task_id="t1",
            agent_id="a",
            session_id=session_id,
            source="api",
            intent="关心用户",
            reason="用户很久没说话",
            created_at=time.time(),
        )
    )
    # 等调度循环 poll 到任务并完成强制话轮
    for _ in range(100):
        if len(channel.replies) >= 2:
            break
        await asyncio.sleep(0.05)
    await am.stop("a")  # 停调度循环

    contents = [r.content for r in channel.replies]
    assert "主动找你聊聊" in contents  # 主动消息真实送达
    # 主动话轮的合成输入带 source/intent/reason
    proactive_input = provider.calls[-1]["messages"][-1]["content"]
    assert "关心用户" in proactive_input and "api" in proactive_input


@pytest.mark.asyncio
async def test_conversation_snapshot_recovery_roundtrip(tmp_path: Path) -> None:
    """L5: 回复后快照落盘 (稳定键) → 重组装 → RecoveryInjector 注入恢复提示。"""
    from isac.runtime.conversation import ConversationStateStore

    provider = SlowFakeProvider(scripted_replies=[make_final_reply("好的")])
    am, channel, drain, _ = await _build_env(provider)
    # 把 state store 指到 tmp 目录 (避免污染仓库 data/)
    instance = await am.get("a")
    instance.services["conversation_state_store"] = ConversationStateStore(base_dir=str(tmp_path))

    await _inject(channel, "记住这个话题")
    await _drain_all(am, drain)

    # 快照按稳定键落盘 (platform:user, 不是重启即变的 sess_*)
    store = ConversationStateStore(base_dir=str(tmp_path))
    snapshots = store.load_all("a")
    assert "fake:user:alice" in snapshots
    assert snapshots["fake:user:alice"].recovery_hint  # 短窗口恢复提示已生成

    # 模拟重启: RecoveryInjector 载入快照后, 同一会话第一轮注入恢复提示
    from isac.agent.injectors.recovery import RecoveryInjector
    from isac.core.types import InjectionContext
    from isac.gateway.models import Session

    injector = RecoveryInjector()
    for key, snap in snapshots.items():
        injector.add_snapshot(key, snap)
    context = InjectionContext(
        session=Session(session_id="sess_new_boot", user_id="alice", platform="fake"),
        user_profile=None,
        current_message=None,
    )
    hint = await injector.build(context)
    assert "内部参考" in hint  # 稳定键命中 (session_id 已变仍能恢复)
    assert await injector.build(context) == ""  # 注入一次后清空


@pytest.mark.asyncio
async def test_wait_tool_woken_by_new_message() -> None:
    """L2: wait 工具挂起期间新消息到达 (锁外信号) → 以 MESSAGE 原因唤醒。"""
    from tests.fixtures.fakes import make_tool_call_response

    provider = SlowFakeProvider(
        scripted_replies=[
            make_tool_call_response("wait", arguments={"seconds": 8}),
            make_final_reply("等到你了"),
            make_final_reply("第二轮回复"),
        ]
    )
    am, channel, drain, _ = await _build_env(provider)

    started = time.monotonic()
    await _inject(channel, "我想想怎么说")  # 第一轮: LLM 调 wait(8s)
    await asyncio.sleep(0.2)  # wait 已挂起
    await _inject(channel, "想好了!")  # 锁外 notify_incoming → resolve_wait(MESSAGE)
    await _drain_all(am, drain)
    elapsed = time.monotonic() - started

    assert elapsed < 5.0  # 远小于 8 秒超时 → 是被消息唤醒而非超时
    # wait 工具结果回填了唤醒原因
    wait_result_msgs = [
        m for call in provider.calls for m in call["messages"] if m.get("role") == "tool"
    ]
    assert any("收到新消息" in m.get("content", "") for m in wait_result_msgs)


@pytest.mark.asyncio
async def test_assembly_wires_idle_reengage_producer_when_configured() -> None:
    """R2-2: conversation.proactive.idle_reengage_seconds > 0 时, 装配出的
    ProactiveScheduler 带真实生产者 (task_producer) —— 主动任务子系统有了真实的
    生产侧入口, 不再是恒空队列。"""
    provider = FakeLLMProvider(scripted_replies=[make_final_reply("ok")])
    am, _ch, _drain, _sm = await _build_env(
        provider, conversation={"proactive": {"idle_reengage_seconds": 60}}
    )
    instance = await am.get("a")
    scheduler = instance.services["proactive_scheduler"]
    assert scheduler._task_producer is not None  # noqa: SLF001


@pytest.mark.asyncio
async def test_assembly_no_producer_by_default() -> None:
    """默认 (未配置 idle_reengage_seconds) 不构造生产者 —— 主链路零行为变化。"""
    provider = FakeLLMProvider(scripted_replies=[make_final_reply("ok")])
    am, _ch, _drain, _sm = await _build_env(provider)
    instance = await am.get("a")
    scheduler = instance.services["proactive_scheduler"]
    assert scheduler._task_producer is None  # noqa: SLF001
