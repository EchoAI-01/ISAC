"""第二轮审查批 3 runtime 修复回归测试 (Fix-81/82/83)。

- Fix-81 (M3): _run_forced_turn 取消在等锁阶段时, finally 不得破坏并发回合的状态机。
- Fix-82 (M4): 强制话轮注入 conversation_runtime (可被打断) + 正常完成清陈旧打断信号。
- Fix-83 (M7): restore_interrupted 先落库改状态再登记内存索引, 无 "running 幻影" 窗口。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from isac.agent.loop import AgentResult
from isac.core.types import AgentContext
from isac.gateway.lock import SessionLockManager
from isac.gateway.models import Session
from isac.runtime.conversation.models import ConversationState, ProactiveTask
from isac.runtime.conversation.runtime import ConversationRuntime
from isac.runtime.manager import AgentManager
from isac.runtime.subagent.models import SubAgentRun
from isac.runtime.subagent.supervisor import SubAgentSupervisor


def _proactive_task() -> ProactiveTask:
    return ProactiveTask(
        task_id="pt1", agent_id="a1", session_id="s1",
        source="memory", intent="关心", reason="用户久未互动",
    )


def _session() -> Session:
    return Session(session_id="s1", user_id="u1", agent_id="a1", platform="fake")


class _FakeLoop:
    def __init__(self, result: AgentResult) -> None:
        self._result = result
        self.contexts: list[AgentContext] = []

    async def run(self, messages: list[dict], context: AgentContext) -> AgentResult:
        self.contexts.append(context)
        return self._result


class _FakeGating:
    def __init__(self) -> None:
        self.replies: list[str] = []

    def get_turn_scheduler(self, session_id: str) -> Any:
        return SimpleNamespace(record_reply=lambda: self.replies.append(session_id))


def _make_manager() -> AgentManager:
    return AgentManager({"session_lock": SessionLockManager()})


def _make_instance(loop: _FakeLoop) -> Any:
    return SimpleNamespace(agent_id="a1", loop=loop, gating=_FakeGating())


# ── Fix-81: 取消路径不破坏并发回合状态机 ─────────────────────


@pytest.mark.asyncio
async def test_forced_turn_cancel_before_lock_does_not_touch_shared_state() -> None:
    """M3: 等锁期间被取消 (turn_owns_state=False) 时不得清别人的 forced_turn、
    不得把并发回合的 THINKING 拨回 IDLE (此前 finally 无条件复位)。"""
    mgr = _make_manager()
    runtime = ConversationRuntime("a1", "s1")
    # 模拟并发回合正持有状态机
    runtime.forced_turn = None
    runtime.transition_to(ConversationState.THINKING)

    lock_mgr = SessionLockManager()
    lock = await lock_mgr.acquire("k")
    await lock.acquire()  # 并发回合持锁
    # 强制话轮协程在等锁处被取消 → 直接走收尾 (turn_owns_state=False)
    mgr._finish_forced_turn(runtime, False, lock_mgr, "k", lock, False)  # noqa: SLF001

    assert runtime.state is ConversationState.THINKING  # 未被误拨 IDLE
    lock.release()
    lock_mgr.release("k")


@pytest.mark.asyncio
async def test_forced_turn_finish_resets_state_it_set() -> None:
    """turn_owns_state=True 时正常复位 forced_turn/THINKING。"""
    mgr = _make_manager()
    runtime = ConversationRuntime("a1", "s1")
    from isac.runtime.conversation.models import ForcedTurnState

    runtime.forced_turn = ForcedTurnState(source="proactive")
    runtime.transition_to(ConversationState.THINKING)
    mgr._finish_forced_turn(runtime, True, None, "k", None, False)  # noqa: SLF001
    assert runtime.forced_turn is None
    assert runtime.state is ConversationState.IDLE


# ── Fix-82: 强制话轮可被打断 + 陈旧打断信号清理 ───────────────


@pytest.mark.asyncio
async def test_forced_turn_injects_conversation_runtime_into_context() -> None:
    """M4-①: loop 的打断判定经 services['conversation_runtime'] 读序号,
    强制话轮不注入则恒不可被打断。"""
    mgr = _make_manager()
    runtime = ConversationRuntime("a1", "s1")
    loop = _FakeLoop(AgentResult(content="你好呀"))
    await mgr._run_forced_turn(_make_instance(loop), _session(), runtime, _proactive_task())  # noqa: SLF001
    assert len(loop.contexts) == 1
    assert loop.contexts[0].services.get("conversation_runtime") is runtime


@pytest.mark.asyncio
async def test_forced_turn_interrupted_keeps_interrupt_state() -> None:
    """M4-②: loop 被打断 (interrupted=True) 时保留 interrupt_state,
    交由接替回合的 InterruptInjector 正常消费。"""
    mgr = _make_manager()
    runtime = ConversationRuntime("a1", "s1")
    runtime.request_interrupt(reason="新消息")
    loop = _FakeLoop(AgentResult(content="", interrupted=True))
    await mgr._run_forced_turn(_make_instance(loop), _session(), runtime, _proactive_task())  # noqa: SLF001
    assert runtime.interrupt_state is not None  # 保留给下一轮注入提示
    assert runtime.state is ConversationState.IDLE
    assert runtime.forced_turn is None


@pytest.mark.asyncio
async def test_forced_turn_normal_completion_clears_stale_interrupt() -> None:
    """M4-②: 正常完成时清除 loop 结束后才到达的陈旧 interrupt_state,
    防止下一回合被注入"上一轮被打断"的错误提示。"""
    mgr = _make_manager()
    runtime = ConversationRuntime("a1", "s1")
    runtime.request_interrupt(reason="迟到的信号")
    loop = _FakeLoop(AgentResult(content="主动问候"))
    await mgr._run_forced_turn(_make_instance(loop), _session(), runtime, _proactive_task())  # noqa: SLF001
    assert runtime.interrupt_state is None  # 陈旧信号已清
    assert runtime.state is ConversationState.IDLE


# ── Fix-83: restore_interrupted 无 running 幻影窗口 ──────────


class _RestoreJournal:
    """restore 返回一个 running run; upsert_run 时记录该 run 是否已在内存索引中。"""

    def __init__(self, run: SubAgentRun) -> None:
        self._run = run
        self.indexed_before_upsert: list[bool] = []
        self._supervisor: SubAgentSupervisor | None = None

    def bind(self, supervisor: SubAgentSupervisor) -> None:
        self._supervisor = supervisor

    async def restore(self) -> list[SubAgentRun]:
        return [self._run]

    async def upsert_run(self, run: SubAgentRun) -> None:
        assert self._supervisor is not None
        # Fix-83: 落库改状态时 run 还不应进入 _runs (否则并发查询可见 running 幻影)
        self.indexed_before_upsert.append(run.task_id in self._supervisor._runs)  # noqa: SLF001


@pytest.mark.asyncio
async def test_restore_interrupted_indexes_runs_only_after_cancel_marked() -> None:
    run = SubAgentRun(task_id="t-old", parent_agent_id="p", status="running")
    journal = _RestoreJournal(run)
    supervisor = SubAgentSupervisor(runner_factory=None, journal=journal)
    journal.bind(supervisor)

    marked = await supervisor.restore_interrupted()

    assert marked == 1
    assert journal.indexed_before_upsert == [False]  # 落库时未入索引
    assert supervisor._runs["t-old"].status == "cancelled"  # noqa: SLF001


# ── L3/L4 (2026-10-13 review): 强制话轮记忆写入 + 主动回复出站保障 ──


@pytest.mark.asyncio
async def test_forced_turn_normal_completion_schedules_memory_write() -> None:
    """L3: 强制话轮正常完成也走 _schedule_memory_write —— 此前仅普通消息路径写
    episodic 记忆 (08-21 盘点遗留③), 主动说过什么/得到什么永不进记忆库。"""
    mgr = _make_manager()
    runtime = ConversationRuntime("a1", "s1")
    loop = _FakeLoop(AgentResult(content="主动问候"))
    calls: list[dict[str, Any]] = []

    def _spy(instance, message, session, user_profile, reply, user_content=None, turn_seq=None):
        calls.append(
            {"reply": reply, "user_content": user_content,
             "profile": user_profile, "turn_seq": turn_seq}
        )

    mgr._schedule_memory_write = _spy  # type: ignore[method-assign]
    await mgr._run_forced_turn(_make_instance(loop), _session(), runtime, _proactive_task())  # noqa: SLF001
    assert len(calls) == 1
    assert calls[0]["reply"] == "主动问候"
    assert calls[0]["user_content"]  # 合成的主动 prompt (含 proactive 标记)
    assert calls[0]["profile"] is None  # 强制话轮无交互画像


@pytest.mark.asyncio
async def test_proactive_reply_retries_then_dead_letters(monkeypatch: pytest.MonkeyPatch) -> None:
    """L4: 主动回复经 outbound._send_reply 投递 —— 失败有界重试 (默认 3 次),
    全败落死信环 (此前 _send_proactive_reply 直发 adapter.send 单次尝试,
    失败仅记日志静默丢, 08-21 盘点遗留④)。"""
    import isac.outbound as outbound_mod

    monkeypatch.setattr(outbound_mod, "_SEND_RETRY_BACKOFF_SECONDS", 0.0)
    dead = outbound_mod.OutboundDeadLetter()
    monkeypatch.setattr(outbound_mod, "_DEFAULT_DEAD_LETTER", dead)

    attempts: list[int] = []

    class _FailAdapter:
        platform_name = "fake"

        async def send(self, message: Any) -> bool:
            attempts.append(1)
            return False

    class _Registry:
        def get(self, platform: str) -> Any:
            return _FailAdapter()

    mgr = AgentManager({"channel_registry": _Registry(), "artifact_store": None})
    instance = SimpleNamespace(agent_id="a1")
    await mgr._deliver_proactive_reply(instance, _session(), "主动内容")  # noqa: SLF001
    assert len(attempts) == outbound_mod._SEND_MAX_ATTEMPTS  # noqa: SLF001
    assert len(dead) == 1  # 全败落死信 (可观测, 不静默丢)

    # 成功路径: 一次即停, 不空转重试。
    attempts.clear()

    class _OkAdapter(_FailAdapter):
        async def send(self, message: Any) -> bool:
            attempts.append(1)
            return True

    class _OkRegistry(_Registry):
        def get(self, platform: str) -> Any:
            return _OkAdapter()

    mgr2 = AgentManager({"channel_registry": _OkRegistry(), "artifact_store": None})
    await mgr2._deliver_proactive_reply(instance, _session(), "主动内容")  # noqa: SLF001
    assert len(attempts) == 1
    assert len(dead) == 1  # 无新增死信


@pytest.mark.asyncio
async def test_proactive_reply_without_registry_logs_and_drops() -> None:
    """无 channel_registry (无 Channel 场景) → 明确告警丢弃, 不抛异常。"""
    mgr = AgentManager({})
    await mgr._deliver_proactive_reply(SimpleNamespace(agent_id="a1"), _session(), "x")  # noqa: SLF001
