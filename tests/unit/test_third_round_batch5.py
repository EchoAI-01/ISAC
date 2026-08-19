"""第三轮审查修复批 5 回归测试 (Fix-111~119: 正确性 + 会话内核)。

- Fix-111: A2A bus.send 补投递超时 (InterAgentTimeoutError) 与递归深度保护
  (InterAgentRecursionError, contextvar 沿投递链传播)。
- Fix-112: observe_message 旁听记忆 episode.user_id 用归一 master_id (与 _write_memory
  同口径), 不再用平台 id 造成键分裂。
- Fix-113: _apply_mesh_routing 退出时还原 primary 的 message.session_id (observer/
  candidate 的 get_or_create 会覆写它)。
- Fix-114: SubAgentSupervisor.cancel 区分"后台任务被取消"(吞) 与"当前任务自身被取消"
  (cancelling()>0 → 重新抛出), 不再无差别吞 CancelledError。
- Fix-115: 强制话轮产出落 U1 事件流 (message.user + turn.completed)。
- Fix-116: 强制话轮取会话锁移入 try, 取锁失败时租约也能被 finally cancel。
- Fix-117: handoff 先预约 SessionWriteGate 再投递摘要 (防半程移交); 仅成功路径 commit,
  失败/异常一律 cancel。
- Fix-118: 主动任务唤醒回调失败重新入队 (attempts 达 MAX_WAKE_RETRIES 才放弃)。
- Fix-119: Agent Loop 预算耗尽退出前发 budget_exhausted 终态进度事件。
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from isac.channel.model import ISACMessage
from isac.core.exceptions import InterAgentRecursionError, InterAgentTimeoutError
from isac.gateway.models import Session, UserProfile
from isac.runtime.bus import InterAgentBus, InterAgentLink, InterAgentMessage
from isac.runtime.conversation.models import ProactiveTask
from isac.runtime.conversation.proactive import ProactiveTaskQueue
from isac.runtime.conversation.scheduler import MAX_WAKE_RETRIES, ProactiveScheduler

# ── Fix-111: bus 超时 + 递归保护 ─────────────────────────────────


def _linked_bus(**kwargs) -> InterAgentBus:
    bus = InterAgentBus(**kwargs)
    bus.add_link(InterAgentLink(from_agent="a1", to_agent="a2", direction="both", enabled=True))
    return bus


@pytest.mark.asyncio
async def test_bus_send_times_out_on_slow_delivery() -> None:
    """目标 Agent 投递挂起时, send 在超时后抛 InterAgentTimeoutError 不再无限等待。"""
    bus = _linked_bus(send_timeout_seconds=0.05)

    async def _slow_deliver(_agent_id: str, _msg: InterAgentMessage) -> str:
        await asyncio.sleep(5)  # 远超超时窗口
        return "too late"

    bus.set_deliver(_slow_deliver)
    with pytest.raises(InterAgentTimeoutError):
        await bus.send(InterAgentMessage(from_agent="a1", to_agent="a2", type="request", content="hi"))


@pytest.mark.asyncio
async def test_bus_send_notify_also_times_out() -> None:
    """notify (fire-and-forget) 同样受超时保护, 不被挂起的投递阻塞。"""
    bus = _linked_bus(send_timeout_seconds=0.05)

    async def _slow_deliver(_agent_id: str, _msg: InterAgentMessage) -> str:
        await asyncio.sleep(5)
        return ""

    bus.set_deliver(_slow_deliver)
    with pytest.raises(InterAgentTimeoutError):
        await bus.send(InterAgentMessage(from_agent="a1", to_agent="a2", type="notify", content="n"))


@pytest.mark.asyncio
async def test_bus_send_completes_within_timeout() -> None:
    """对照组: 快速投递在超时窗口内正常返回响应, 不受新防护影响。"""
    bus = _linked_bus(send_timeout_seconds=1.0)

    async def _fast_deliver(_agent_id: str, _msg: InterAgentMessage) -> str:
        return "ok"

    bus.set_deliver(_fast_deliver)
    resp = await bus.send(
        InterAgentMessage(from_agent="a1", to_agent="a2", type="request", content="hi")
    )
    assert resp is not None
    assert resp.content == "ok"


@pytest.mark.asyncio
async def test_bus_send_rejects_nested_recursion() -> None:
    """A 调 B、B 的投递里又调 A —— 嵌套深度超限时抛 InterAgentRecursionError。"""
    bus = _linked_bus(max_delivery_depth=1)

    async def _recursive_deliver(agent_id: str, msg: InterAgentMessage) -> str:
        # 投递处理内再发起一次反向 send → 深度 +1, 超限被拒
        other = "a1" if agent_id == "a2" else "a2"
        await bus.send(InterAgentMessage(from_agent=agent_id, to_agent=other, type="request", content="nested"))
        return "never"

    bus.set_deliver(_recursive_deliver)
    with pytest.raises(InterAgentRecursionError):
        await bus.send(InterAgentMessage(from_agent="a1", to_agent="a2", type="request", content="hi"))


@pytest.mark.asyncio
async def test_bus_recursion_guard_does_not_affect_flat_calls() -> None:
    """对照组: 无嵌套的平级连续 send 不受递归计数影响 (depth 不跨调用累积)。"""
    bus = _linked_bus(max_delivery_depth=1)

    async def _deliver(_agent_id: str, _msg: InterAgentMessage) -> str:
        return "ok"

    bus.set_deliver(_deliver)
    for _ in range(3):
        resp = await bus.send(
            InterAgentMessage(from_agent="a1", to_agent="a2", type="request", content="hi")
        )
        assert resp is not None


# ── Fix-112: observe_message master_id 口径 ──────────────────────


class _RecordingMemory:
    """记录 store_episode 调用的假记忆管线 (无 metadata 属性 → _update_person_profile 早退)。"""

    def __init__(self) -> None:
        self.episodes: list[dict] = []

    async def store_episode(self, **kwargs) -> None:
        self.episodes.append(kwargs)


@pytest.mark.asyncio
async def test_observe_message_uses_master_id() -> None:
    """旁听写入的 episode.user_id 用 user_profile.user_id (master_id) 而非平台 id。"""
    from isac.memory.pipeline import NoOpMemoryPipeline
    from isac.provider.llm.stub import StubProvider
    from isac.provider.manager import ProviderManager
    from isac.runtime.config import AgentConfig
    from isac.runtime.manager import AgentManager

    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    manager = AgentManager(
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        }
    )
    await manager.create(AgentConfig(agent_id="agent_a"))
    await manager.start("agent_a")
    instance = await manager.get("agent_a")
    assert instance is not None
    memory = _RecordingMemory()
    instance.memory = memory  # type: ignore[assignment]

    message = ISACMessage(
        msg_id="m1", platform="webchat", timestamp=0,
        user_id="platform_uid", user_name="某人", content="旁听内容",
    )
    session = Session(session_id="s1", user_id="master_uid", agent_id="agent_a", platform="webchat")
    profile = UserProfile(user_id="master_uid", nickname="某人")
    await manager.observe_message("agent_a", message, session, profile)

    assert len(memory.episodes) == 1
    assert memory.episodes[0]["user_id"] == "master_uid"  # master_id, 非 platform_uid


@pytest.mark.asyncio
async def test_observe_message_falls_back_to_platform_id_without_profile() -> None:
    """对照组: user_profile 为 None 时回退平台 id (向后兼容)。"""
    from isac.memory.pipeline import NoOpMemoryPipeline
    from isac.provider.llm.stub import StubProvider
    from isac.provider.manager import ProviderManager
    from isac.runtime.config import AgentConfig
    from isac.runtime.manager import AgentManager

    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    manager = AgentManager(
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        }
    )
    await manager.create(AgentConfig(agent_id="agent_a"))
    await manager.start("agent_a")
    instance = await manager.get("agent_a")
    assert instance is not None
    memory = _RecordingMemory()
    instance.memory = memory  # type: ignore[assignment]

    message = ISACMessage(
        msg_id="m1", platform="webchat", timestamp=0,
        user_id="platform_uid", user_name="某人", content="旁听内容",
    )
    session = Session(session_id="s1", user_id="platform_uid", agent_id="agent_a", platform="webchat")
    await manager.observe_message("agent_a", message, session, None)

    assert len(memory.episodes) == 1
    assert memory.episodes[0]["user_id"] == "platform_uid"


# ── Fix-113: _apply_mesh_routing 还原 session_id ─────────────────


class _FakeMeshAgentManager:
    def __init__(self, roles: dict[str, str]) -> None:
        self._roles = roles
        self.observed: list[str] = []

    def mesh_roles(self) -> dict[str, str]:
        return self._roles

    def schedule_observe_message(self, agent_id, message, session, profile) -> None:
        self.observed.append(agent_id)

    async def gating_score(self, agent_id, message, session, profile) -> float:
        return 0.0


@pytest.mark.asyncio
async def test_apply_mesh_routing_restores_primary_session_id() -> None:
    """observer 的 get_or_create 覆写 message.session_id 后, 退出时还原为 primary 的。"""
    from isac.dispatch import _apply_mesh_routing
    from isac.gateway.session import SessionManager

    session_mgr = SessionManager()
    message = ISACMessage(
        msg_id="m1", platform="webchat", timestamp=0,
        user_id="u1", user_name="u1", content="hi",
    )
    # primary 会话先行建立 (dispatcher 的实际顺序)
    primary_session = await session_mgr.get_or_create(message, agent_id="primary_agent")
    primary_session_id = message.session_id
    assert primary_session_id

    fake_am = _FakeMeshAgentManager({"obs1": "observer"})
    decision = SimpleNamespace(agent_id="primary_agent", matched_by="default", content="hi")
    result = await _apply_mesh_routing(decision, message, primary_session, None, session_mgr, fake_am)

    assert result == "primary_agent"
    assert fake_am.observed == ["obs1"]  # observer 确实被安排旁听
    assert message.session_id == primary_session_id  # 还原, 不残留 observer 的会话 id


@pytest.mark.asyncio
async def test_apply_mesh_routing_no_roles_zero_change() -> None:
    """对照组: 无 mesh 角色配置时短路返回, 不动 session_id。"""
    from isac.dispatch import _apply_mesh_routing
    from isac.gateway.session import SessionManager

    session_mgr = SessionManager()
    message = ISACMessage(
        msg_id="m1", platform="webchat", timestamp=0, user_id="u1", user_name="u1", content="hi"
    )
    session = await session_mgr.get_or_create(message, agent_id="primary_agent")
    original = message.session_id
    fake_am = _FakeMeshAgentManager({})
    decision = SimpleNamespace(agent_id="primary_agent", matched_by="default", content="hi")
    result = await _apply_mesh_routing(decision, message, session, None, session_mgr, fake_am)
    assert result == "primary_agent"
    assert message.session_id == original


# ── Fix-114: cancel 区分两种 CancelledError ──────────────────────


@pytest.mark.asyncio
async def test_cancel_running_task_still_works() -> None:
    """正常路径: cancel 后台任务, CancelledError 来自后台任务 → 吞掉, 状态 cancelled。"""
    from isac.runtime.subagent.models import SubAgentResult, SubAgentTask
    from isac.runtime.subagent.supervisor import SubAgentSupervisor

    started = asyncio.Event()

    async def _runner(task: SubAgentTask) -> SubAgentResult:
        started.set()
        await asyncio.sleep(5)
        return SubAgentResult(task_id=task.task_id, status="succeeded", summary="never")

    supervisor = SubAgentSupervisor(runner_factory=_runner)
    task = SubAgentTask(
        task_id="c1", parent_agent_id="parent", session_id="s1", trace_id="tr1", objective="g"
    )
    await supervisor.submit(task)
    await asyncio.wait_for(started.wait(), timeout=1.0)
    cancelled = await supervisor.cancel("c1")
    assert cancelled is not None
    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_propagates_when_current_task_cancelled() -> None:
    """当前任务自身被取消时 (cancelling()>0), cancel 必须重新抛出 CancelledError。

    用"抗取消"的 runner 使场景确定: bg_task 捕获 CancelledError 不退出, 于是
    `await wait_for(shield(bg_task))` 会一直阻塞到宽限期 —— 在这段阻塞窗口内取消
    调用 cancel() 的当前任务, CancelledError 只能来自当前任务自身 (cancelling()>0),
    修复后的分支必须重新抛出 (旧实现会吞掉, 取消协议失效)。
    """
    from isac.runtime.subagent.models import SubAgentResult, SubAgentTask
    from isac.runtime.subagent.supervisor import SubAgentSupervisor

    started = asyncio.Event()

    async def _stubborn_runner(task: SubAgentTask) -> SubAgentResult:
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(10)  # 吞掉取消, 拒绝退出
        return SubAgentResult(task_id=task.task_id, status="succeeded", summary="x")

    supervisor = SubAgentSupervisor(runner_factory=_stubborn_runner, cancel_grace_seconds=2.0)
    task = SubAgentTask(
        task_id="c2", parent_agent_id="parent", session_id="s1", trace_id="tr1", objective="g"
    )
    await supervisor.submit(task)
    await asyncio.wait_for(started.wait(), timeout=1.0)

    # 在另一个任务里调 cancel (会阻塞在宽限期窗口), 随即取消该任务自身。
    async def _cancel_and_be_cancelled() -> None:
        await supervisor.cancel("c2")

    cancel_task = asyncio.create_task(_cancel_and_be_cancelled())
    await asyncio.sleep(0.05)  # 让 cancel_task 进入 cancel 内部的 wait_for 阻塞窗口
    cancel_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancel_task


# ── Fix-118: 主动任务唤醒失败重入队 ──────────────────────────────


def _proactive_task(task_id: str = "t1", session_id: str = "s1") -> ProactiveTask:
    return ProactiveTask(
        task_id=task_id, agent_id="a1", session_id=session_id,
        source="memory", intent="remind", reason="提醒", created_at=time.time(),
    )


@pytest.mark.asyncio
async def test_fire_task_requeues_on_callback_failure() -> None:
    queue = ProactiveTaskQueue()
    sched = ProactiveScheduler(queue=queue, min_interval_seconds=0.0)

    async def _failing_wake(_task: ProactiveTask) -> None:
        raise RuntimeError("wake boom")

    sched._wake_callback = _failing_wake
    task = _proactive_task()
    assert len(queue) == 0
    await sched._fire_task(task)
    assert task.attempts == 1
    assert len(queue) == 1  # 重新入队


@pytest.mark.asyncio
async def test_fire_task_gives_up_after_max_retries() -> None:
    queue = ProactiveTaskQueue()
    sched = ProactiveScheduler(queue=queue, min_interval_seconds=0.0)

    async def _failing_wake(_task: ProactiveTask) -> None:
        raise RuntimeError("wake boom")

    sched._wake_callback = _failing_wake
    task = _proactive_task()
    task.attempts = MAX_WAKE_RETRIES - 1  # 再失败一次即达上限
    await sched._fire_task(task)
    assert task.attempts == MAX_WAKE_RETRIES
    assert len(queue) == 0  # 重试耗尽, 放弃且不再入队


@pytest.mark.asyncio
async def test_fire_task_success_does_not_requeue() -> None:
    queue = ProactiveTaskQueue()
    sched = ProactiveScheduler(queue=queue, min_interval_seconds=0.0)
    called = []

    async def _ok_wake(task: ProactiveTask) -> None:
        called.append(task.task_id)

    sched._wake_callback = _ok_wake
    task = _proactive_task()
    await sched._fire_task(task)
    assert called == ["t1"]
    assert len(queue) == 0  # 成功不重入队


# ── Fix-119: 预算耗尽终态进度事件 ────────────────────────────────


def test_budget_exhausted_is_terminal_stage() -> None:
    """budget_exhausted 登记为终态/任务级终态, 并有人设模板。"""
    from isac.runtime.progress import (
        _TASK_TERMINAL_STAGES,
        _TERMINAL_STAGES,
        PersonaProgressRenderer,
    )

    assert "budget_exhausted" in _TERMINAL_STAGES
    assert "budget_exhausted" in _TASK_TERMINAL_STAGES
    assert "budget_exhausted" in PersonaProgressRenderer._STAGE_TEMPLATES


# ── Fix-115: 强制话轮产出落 U1 事件 ──────────────────────────────


class _FakeEventStore:
    def __init__(self) -> None:
        self.events: list = []

    async def append(self, event) -> int:
        self.events.append(event)
        return len(self.events)

    async def flush(self) -> None:
        pass


def _make_session_manager_for_history() -> SimpleNamespace:
    return SimpleNamespace(
        make_session_key=lambda agent_id, platform, user_id, group_id: f"{agent_id}:{platform}:{user_id}"
    )


@pytest.mark.asyncio
async def test_forced_turn_records_u1_events() -> None:
    """Fix-115: 强制话轮正常完成时, 合成 prompt 与回复成对落 U1 事件流。"""
    from isac.agent.loop import AgentResult
    from isac.core.types import AgentContext
    from isac.gateway.lock import SessionLockManager
    from isac.runtime.conversation.models import ProactiveTask
    from isac.runtime.conversation.runtime import ConversationRuntime
    from isac.runtime.manager import AgentManager
    from isac.session.models import EVENT_TURN_COMPLETED, EVENT_USER_MESSAGE

    class _Loop:
        def __init__(self, result: AgentResult) -> None:
            self._result = result

        async def run(self, messages, context: AgentContext) -> AgentResult:
            return self._result

    class _Gating:
        def get_turn_scheduler(self, session_id):
            return SimpleNamespace(record_reply=lambda: None)

    store = _FakeEventStore()
    mgr = AgentManager(
        {
            "session_lock": SessionLockManager(),
            "session_event_store": store,
            "session_history": SimpleNamespace(),
            "session_mgr": _make_session_manager_for_history(),
            "global_config": {},
        }
    )
    runtime = ConversationRuntime("a1", "s1")
    session = Session(session_id="s1", user_id="u1", agent_id="a1", platform="fake")
    task = ProactiveTask(
        task_id="pt1", agent_id="a1", session_id="s1",
        source="memory", intent="关心", reason="用户久未互动",
    )
    instance = SimpleNamespace(agent_id="a1", loop=_Loop(AgentResult(content="主动问候")), gating=_Gating())
    await mgr._run_forced_turn(instance, session, runtime, task)  # noqa: SLF001

    types = [e.event_type for e in store.events]
    assert EVENT_USER_MESSAGE in types  # 合成 prompt (带 proactive 标记)
    assert EVENT_TURN_COMPLETED in types  # 回复
    completed = next(e for e in store.events if e.event_type == EVENT_TURN_COMPLETED)
    assert completed.payload["content"] == "主动问候"
    user_ev = next(e for e in store.events if e.event_type == EVENT_USER_MESSAGE)
    assert user_ev.payload.get("proactive") is True


@pytest.mark.asyncio
async def test_forced_turn_no_events_when_history_disabled() -> None:
    """对照组: session_event_store 未注入时零行为变化 (不落事件, 不报错)。"""
    from isac.agent.loop import AgentResult
    from isac.core.types import AgentContext
    from isac.gateway.lock import SessionLockManager
    from isac.runtime.conversation.models import ProactiveTask
    from isac.runtime.conversation.runtime import ConversationRuntime
    from isac.runtime.manager import AgentManager

    class _Loop:
        async def run(self, messages, context: AgentContext) -> AgentResult:
            return AgentResult(content="主动问候")

    class _Gating:
        def get_turn_scheduler(self, session_id):
            return SimpleNamespace(record_reply=lambda: None)

    mgr = AgentManager({"session_lock": SessionLockManager(), "global_config": {}})
    runtime = ConversationRuntime("a1", "s1")
    session = Session(session_id="s1", user_id="u1", agent_id="a1", platform="fake")
    task = ProactiveTask(
        task_id="pt1", agent_id="a1", session_id="s1", source="memory", intent="i", reason="r"
    )
    instance = SimpleNamespace(agent_id="a1", loop=_Loop(), gating=_Gating())
    # 无 session_event_store → _history_parts 返回 None, 静默跳过
    await mgr._run_forced_turn(instance, session, runtime, task)  # noqa: SLF001


# ── Fix-116: 强制话轮租约在取锁失败时也能被 cancel ───────────────


class _RaisingLockManager:
    async def acquire(self, key: str):
        raise RuntimeError("lock boom")

    def release(self, key: str) -> None:
        pass


@pytest.mark.asyncio
async def test_forced_turn_cancels_lease_when_lock_acquire_fails() -> None:
    """Fix-116: 取会话锁移入 try —— 预约到租约后若取锁阶段异常, finally 必须 cancel
    租约, 不得泄漏到 hold 超时 (期间挡住该会话的其他写入)。"""
    from isac.agent.loop import AgentResult
    from isac.core.types import AgentContext
    from isac.runtime.conversation.models import ProactiveTask
    from isac.runtime.conversation.runtime import ConversationRuntime
    from isac.runtime.manager import AgentManager
    from isac.runtime.write_gate import SessionWriteGate

    class _Loop:
        async def run(self, messages, context: AgentContext) -> AgentResult:
            return AgentResult(content="x")

    class _Gating:
        def get_turn_scheduler(self, session_id):
            return SimpleNamespace(record_reply=lambda: None)

    gate = SessionWriteGate()
    mgr = AgentManager(
        {"session_lock": _RaisingLockManager(), "session_write_gate": gate, "global_config": {}}
    )
    runtime = ConversationRuntime("a1", "s1")
    session = Session(session_id="s1", user_id="u1", agent_id="a1", platform="fake")
    task = ProactiveTask(
        task_id="pt1", agent_id="a1", session_id="s1", source="memory", intent="i", reason="r"
    )
    instance = SimpleNamespace(agent_id="a1", loop=_Loop(), gating=_Gating())
    await mgr._run_forced_turn(instance, session, runtime, task)  # noqa: SLF001

    # 取锁失败但租约已被 cancel, 会话写入面立即可用 (无泄漏的活跃租约)
    assert gate.active("s1") is None
    assert len(gate) == 0


# ── Fix-117: handoff 先预约后投递 + 仅成功 commit ────────────────


class _FakeBroker:
    def __init__(self, ok: bool) -> None:
        self._ok = ok
        self.handoff_calls: list[tuple[str, str]] = []

    async def handoff(self, from_agent: str, to_agent: str, summary: str, policy=None) -> bool:
        self.handoff_calls.append((from_agent, to_agent))
        return self._ok


class _FakeRouter:
    def __init__(self) -> None:
        self.set_calls: list = []
        self.clear_calls: list = []

    def is_agent_routable(self, agent_id: str) -> bool:
        return True

    def set_handoff(self, platform, group_id, user_id, target) -> None:
        self.set_calls.append((platform, group_id, user_id, target))

    def clear_handoff(self, platform, group_id, user_id) -> None:
        self.clear_calls.append((platform, group_id, user_id))


def _handoff_context(broker, router, gate, session) -> object:
    from isac.agent.tools.base import ToolContext
    from isac.core.types import AgentContext

    msg = ISACMessage(
        msg_id="m1", platform="fake", timestamp=0, user_id="u1", user_name="u1", content="hi"
    )
    agent_context = AgentContext(session=session, user_profile=None, current_message=msg)
    return ToolContext(
        args={"target_agent": "agent_b", "summary": "交接摘要"},
        agent_context=agent_context,
        services={
            "mesh_action_broker": broker,
            "agent_id": "agent_a",
            "router": router,
            "session_write_gate": gate,
        },
    )


@pytest.mark.asyncio
async def test_handoff_reserves_gate_before_delivery() -> None:
    """Fix-117①: 会话已有活跃租约 (预约失败) 时不得投递摘要 —— 避免半程移交。"""
    from isac.agent.tools.social.handoff_conversation import HandoffConversationTool
    from isac.runtime.write_gate import SessionWriteGate

    gate = SessionWriteGate()
    session = Session(session_id="s1", user_id="u1", agent_id="agent_a", platform="fake")
    # 预先占用该会话的写入租约 (模拟在途写入)
    blocker = gate.reserve("s1", "proactive")
    assert blocker is not None

    broker = _FakeBroker(ok=True)
    router = _FakeRouter()
    ctx = _handoff_context(broker, router, gate, session)
    result = await HandoffConversationTool().execute(ctx)  # type: ignore[arg-type]

    assert result.is_error
    assert broker.handoff_calls == []  # 预约失败 → 未投递摘要
    assert router.set_calls == []


@pytest.mark.asyncio
async def test_handoff_commits_only_on_success() -> None:
    """Fix-117②: 成功路径 commit (归属转移生效); broker 失败则 cancel 且不转移归属。"""
    from isac.agent.tools.social.handoff_conversation import HandoffConversationTool
    from isac.runtime.write_gate import SessionWriteGate

    # 成功路径
    gate = SessionWriteGate()
    session = Session(session_id="s1", user_id="u1", agent_id="agent_a", platform="fake")
    broker = _FakeBroker(ok=True)
    router = _FakeRouter()
    ctx = _handoff_context(broker, router, gate, session)
    result = await HandoffConversationTool().execute(ctx)  # type: ignore[arg-type]
    assert not result.is_error
    assert router.set_calls == [("fake", None, "u1", "agent_b")]
    assert gate.active("s1") is None  # commit 后无活跃租约

    # 失败路径: broker 拒绝 → 不转移归属, 租约被 cancel
    gate2 = SessionWriteGate()
    broker2 = _FakeBroker(ok=False)
    router2 = _FakeRouter()
    ctx2 = _handoff_context(broker2, router2, gate2, session)
    result2 = await HandoffConversationTool().execute(ctx2)  # type: ignore[arg-type]
    assert result2.is_error
    assert router2.set_calls == []  # 归属未转移
    assert gate2.active("s1") is None  # 租约已 cancel, 无泄漏


class _CommitFailingGate:
    """reserve 成功但 commit 恒失败 (模拟租约在 hold 期内过期)。"""

    def reserve(self, session_key: str, source: str):
        return SimpleNamespace(session_key=session_key, source=source)

    def commit(self, reservation) -> bool:
        return False

    def cancel(self, reservation) -> None:
        return None


@pytest.mark.asyncio
async def test_handoff_commit_failure_skips_ownership_transfer() -> None:
    """2026-08-19 (H3) fail-closed 回归: 租约 commit 失败 (过期) 时不得执行归属转移。

    此前先 _transfer_ownership 再 commit, commit 失败只记 warning、归属不回滚。
    现 commit 前置于归属转移, 失败则放弃移交 (对照 manager 强制话轮 commit 通过
    才推送产出)。断言: router.set_handoff 零调用 + 返回 is_error。
    """
    from isac.agent.tools.social.handoff_conversation import HandoffConversationTool

    class _OkBroker:
        async def handoff(self, *args, **kwargs) -> bool:
            return True

    session = Session(session_id="s1", user_id="u1", agent_id="agent_a", platform="fake")
    router = _FakeRouter()
    ctx = _handoff_context(_OkBroker(), router, _CommitFailingGate(), session)
    result = await HandoffConversationTool().execute(ctx)  # type: ignore[arg-type]
    assert result.is_error
    assert router.set_calls == []  # commit 失败 → 归属未转移 (fail-closed)
