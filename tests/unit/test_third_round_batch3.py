"""第三轮审查修复批 3 回归测试 (Fix-100~103: 会话内核正确性)。

- Fix-100: 打断回合的孤儿 user 事件由 turn.aborted 补偿事件标记作废, fold 跳过,
  接替回合重复落同一 burst 后历史窗口不出现重复用户内容。
- Fix-101: 命令短路返回不得吞掉 Fix-57 回拨的积压 burst —— 命令命中且存在被打断
  回拨输入时, 非命令输入接续为正常回合 (门控→Loop→回复)。
- Fix-102: ArtifactStore 重复 put 同内容时 expires_at 只延长不缩短 (0=永不过期优先),
  kind/mime/metadata 仍以首次登记为准 (Fix-69 语义不变)。
- Fix-103: SessionManager per-key 锁引用计数 —— 持锁 (含"已取出未持有"窗口) 期间
  注册表条目不被 GC, 后来者拿到同一把锁串行 check-then-create, 无双创建。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from isac.artifacts.store import ArtifactStore
from isac.channel.model import ISACMessage, MessageSegment
from isac.commands.base import Command
from isac.commands.registry import CommandRegistry
from isac.core.types import AgentContext
from isac.gateway.models import Session
from isac.gateway.session import SessionManager
from isac.memory.pipeline import NoOpMemoryPipeline
from isac.provider.manager import ProviderManager
from isac.runtime.config import AgentConfig
from isac.runtime.conversation.runtime import ConversationRuntime
from isac.runtime.manager import AgentManager
from isac.session.history import SessionHistoryDeriver
from isac.session.models import (
    EVENT_TURN_ABORTED,
    EVENT_TURN_COMPLETED,
    EVENT_USER_MESSAGE,
    IGNORABLE_EVENT_TYPES,
    SessionEvent,
)
from tests.fixtures.fakes import FakeLLMProvider, make_final_reply

KEY = "agent_a:webchat:group:G1"
AGENT_ID = "agent_a"


# ── Fix-100: turn.aborted 补偿事件 ────────────────────────────────


def test_turn_aborted_is_ignorable_for_forward_compat() -> None:
    """turn.aborted 登记为 ignorable: 旧版本重建安全跳过不崩溃。"""
    assert EVENT_TURN_ABORTED in IGNORABLE_EVENT_TYPES
    ev = SessionEvent(session_key=KEY, event_type=EVENT_TURN_ABORTED, timestamp=1, seq=1)
    assert ev.is_ignorable()


def test_fold_skips_aborted_user_event_and_marker() -> None:
    """被打断的孤儿 user 事件 + 补偿事件本身都不进历史。"""
    events = [
        SessionEvent(KEY, EVENT_USER_MESSAGE, 1, {"content": "Q1"}, seq=1),
        SessionEvent(KEY, EVENT_TURN_ABORTED, 1, {"aborted_user_seq": 1}, seq=2),
        SessionEvent(KEY, EVENT_USER_MESSAGE, 1, {"content": "Q1"}, seq=3),
        SessionEvent(KEY, EVENT_TURN_COMPLETED, 1, {"content": "A1"}, seq=4),
    ]
    messages = SessionHistoryDeriver().fold(events)
    assert messages == [
        {"role": "user", "content": "Q1"},
        {"role": "assistant", "content": "A1"},
    ]


def test_derive_window_no_duplicate_user_content_after_interrupt() -> None:
    """回归场景: Q1 回合被打断 (回复抑制) → 接替回合重新 drain 同一 burst 再落一条
    相同内容 user 事件 → 窗口里 Q1 只出现一次。"""
    events = [
        SessionEvent(KEY, EVENT_USER_MESSAGE, 1, {"content": "刚才那条没看到回复"}, seq=1),
        SessionEvent(KEY, EVENT_TURN_ABORTED, 1, {"aborted_user_seq": 1}, seq=2),
        SessionEvent(KEY, EVENT_USER_MESSAGE, 1, {"content": "刚才那条没看到回复"}, seq=3),
        SessionEvent(KEY, EVENT_TURN_COMPLETED, 1, {"content": "抱歉, 在的"}, seq=4),
    ]
    window = SessionHistoryDeriver(window_turns=10).derive_window(events)
    user_msgs = [m for m in window if m["role"] == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0]["content"] == "刚才那条没看到回复"


def test_fold_without_abort_marker_keeps_both_user_events() -> None:
    """对照组: 无补偿事件时两条 user 事件都保留 (不误伤正常重复发言)。"""
    events = [
        SessionEvent(KEY, EVENT_USER_MESSAGE, 1, {"content": "Q1"}, seq=1),
        SessionEvent(KEY, EVENT_USER_MESSAGE, 1, {"content": "Q1"}, seq=2),
        SessionEvent(KEY, EVENT_TURN_COMPLETED, 1, {"content": "A1"}, seq=3),
    ]
    messages = SessionHistoryDeriver().fold(events)
    assert len([m for m in messages if m["role"] == "user"]) == 2


# ── Fix-101: 命令分支接续被打断的积压输入 ─────────────────────────


class _PingCommand(Command):
    @property
    def name(self) -> str:
        return "ping"

    async def execute(self, message: ISACMessage, args: str, context: AgentContext) -> str:
        return "pong"


def _at_message(msg_id: str, user_id: str, content: str) -> ISACMessage:
    """带 @ 分段的消息, 强制门控直接 TRIGGER。"""
    return ISACMessage(
        msg_id=msg_id,
        platform="webchat",
        timestamp=0,
        user_id=user_id,
        user_name=user_id,
        content=content,
        segments=[MessageSegment(type="at", data={})],
    )


async def _make_manager_with_provider(provider: object) -> AgentManager:
    provider_manager = ProviderManager({})
    provider_manager.register(provider)  # type: ignore[arg-type]
    manager = AgentManager(
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        }
    )
    await manager.create(AgentConfig(agent_id=AGENT_ID))
    await manager.start(AGENT_ID)
    return manager


@pytest.mark.asyncio
async def test_command_branch_continues_interrupted_input() -> None:
    """Fix-101 回归: 问题 Q1 → 回合被打断 (Fix-57 回拨缓存) → /ping 命令分支 drain
    出 Q1 → Q1 接续为正常回合进 LLM, 而不是被命令短路永久吞掉。"""
    provider = FakeLLMProvider(scripted_replies=[make_final_reply("接续 Q1 的回复")])
    manager = await _make_manager_with_provider(provider)
    instance = await manager.get(AGENT_ID)
    assert instance is not None

    registry = CommandRegistry()
    registry.register(_PingCommand())
    instance.commands = registry

    session = Session(session_id="sess_cmd", user_id="u1", agent_id=AGENT_ID)
    runtime = ConversationRuntime(AGENT_ID, session.session_id)
    q1 = _at_message("m_q1", "u1", "帮我查一下天气")
    runtime.register_message(q1)  # Fix-57 回拨后滞留缓存的被打断输入
    # conversation 未启用 (global_config 为空), 直接替换运行时解析返回预置 runtime
    manager._conversation_runtime_for = lambda inst, sess, msg: runtime  # type: ignore[method-assign]

    reply = await manager.handle_message(
        AGENT_ID, _at_message("m_cmd", "u1", "/ping"), session, None
    )

    # Q1 接续为正常回合: LLM 看到的是 Q1 内容, 返回的是回合回复而非命令输出
    assert reply == "接续 Q1 的回复"
    assert len(provider.calls) == 1
    contents = [m["content"] for m in provider.calls[0]["messages"] if m["role"] == "user"]
    assert any("帮我查一下天气" in c for c in contents)


@pytest.mark.asyncio
async def test_command_branch_without_interrupted_input_returns_cmd_result() -> None:
    """对照组: 无积压输入时命令短路返回命令结果, 不走 LLM (零行为变化)。"""
    provider = FakeLLMProvider(scripted_replies=[make_final_reply("不该出现")])
    manager = await _make_manager_with_provider(provider)
    instance = await manager.get(AGENT_ID)
    assert instance is not None

    registry = CommandRegistry()
    registry.register(_PingCommand())
    instance.commands = registry

    session = Session(session_id="sess_cmd2", user_id="u1", agent_id=AGENT_ID)
    runtime = ConversationRuntime(AGENT_ID, session.session_id)
    manager._conversation_runtime_for = lambda inst, sess, msg: runtime  # type: ignore[method-assign]

    reply = await manager.handle_message(
        AGENT_ID, _at_message("m_cmd", "u1", "/ping"), session, None
    )
    assert reply == "pong"
    assert provider.calls == []  # 命令短路不进 LLM


# ── Fix-102: ArtifactStore TTL 只延长不缩短 ───────────────────────


@pytest.mark.asyncio
async def test_repeat_put_extends_ttl_only(tmp_path: Path) -> None:
    store = ArtifactStore(str(tmp_path / "art"))
    data = b"same-content-bytes"
    now = int(time.time())
    await store.put(data, kind="file", expires_at=now + 100)
    ref_longer = await store.put(data, kind="file", expires_at=now + 5000)
    assert ref_longer.expires_at == now + 5000
    # 更短的新 TTL 不得缩短既有 TTL
    ref_shorter = await store.put(data, kind="file", expires_at=now + 1)
    assert ref_shorter.expires_at == now + 5000


@pytest.mark.asyncio
async def test_repeat_put_never_expire_dominates(tmp_path: Path) -> None:
    store = ArtifactStore(str(tmp_path / "art"))
    data = b"persist-forever"
    now = int(time.time())
    await store.put(data, kind="file", expires_at=now + 100)
    ref = await store.put(data, kind="file", expires_at=0)  # 0 = 永不过期
    assert ref.expires_at == 0


@pytest.mark.asyncio
async def test_expired_registration_refreshed_by_new_put(tmp_path: Path) -> None:
    """回归场景本身: 首次注册的短 TTL 已过期 (sweep 未及清扫), 再次 put 同内容
    拿到的 ref 必须可用 —— 此前 INSERT OR IGNORE 保留过期 TTL, get 直接删文件。"""
    store = ArtifactStore(str(tmp_path / "art"))
    data = b"revive-me"
    now = int(time.time())
    ref_expired = await store.put(data, kind="file", expires_at=now - 10)
    assert ref_expired.expires_at < now  # 首次登记即已过期
    ref_fresh = await store.put(data, kind="file", expires_at=now + 3600)
    assert ref_fresh.expires_at == now + 3600
    got = await store.get(ref_fresh.artifact_id)
    assert got == data


@pytest.mark.asyncio
async def test_repeat_put_still_keeps_first_registration_metadata(tmp_path: Path) -> None:
    """Fix-69 语义不变: kind/mime/metadata 以首次登记为准, 只有 TTL 被延长。"""
    store = ArtifactStore(str(tmp_path / "art"))
    data = b"meta-content"
    now = int(time.time())
    await store.put(
        data, kind="image", mime_type="image/png", metadata={"a": 1}, expires_at=now + 100
    )
    ref = await store.put(
        data,
        kind="file",
        mime_type="application/octet-stream",
        metadata={"b": 2},
        expires_at=now + 5000,
    )
    assert ref.kind == "image"
    assert ref.mime_type == "image/png"
    assert ref.metadata == {"a": 1}
    assert ref.expires_at == now + 5000


# ── Fix-103: per-key 锁引用计数防竞态回收 ─────────────────────────


@pytest.mark.asyncio
async def test_concurrent_get_or_create_same_key_single_identity() -> None:
    mgr = SessionManager({"session_ttl_seconds": 3600})
    msg = ISACMessage(
        msg_id="m1", platform="webchat", timestamp=0, user_id="u1", user_name="u1", content="hi"
    )
    sessions = await asyncio.gather(*(mgr.get_or_create(msg, AGENT_ID) for _ in range(16)))
    assert len({s.session_id for s in sessions}) == 1
    assert mgr._key_locks == {}  # 引用计数归零自排空, 注册表无界增长已消除


@pytest.mark.asyncio
async def test_held_key_lock_survives_gc_and_serializes_latecomers() -> None:
    """回归竞态: 持锁期间 (含已取出未持有的窗口) 跑 _gc_expired 不得删注册表条目;
    后来者必须拿到**同一把锁**被串行, 而非新建锁并行 check-then-create。"""
    mgr = SessionManager({"session_ttl_seconds": 3600})
    key = f"{AGENT_ID}:webchat:user:u1"
    entered: list[asyncio.Lock] = []

    async def holder() -> None:
        async with mgr._held_key_lock(key) as lock:
            entered.append(lock)
            await asyncio.sleep(0.05)

    t1 = asyncio.create_task(holder())
    await asyncio.sleep(0.01)  # t1 已取出锁并持有
    mgr._gc_expired()  # 旧实现可能在此删掉注册表条目 → 后来者拿新锁并行
    assert key in mgr._key_locks  # 引用计数 > 0 时条目不可回收

    async def latecomer() -> None:
        async with mgr._held_key_lock(key) as lock:
            entered.append(lock)

    t2 = asyncio.create_task(latecomer())
    await asyncio.sleep(0.02)  # t1 仍在持有, t2 必须被同一把锁挡住
    assert len(entered) == 1
    await asyncio.gather(t1, t2)
    assert len(entered) == 2
    assert entered[0] is entered[1]  # 同一锁对象 → check-then-create 串行
    assert mgr._key_locks == {}  # 全部释放后条目自排空


@pytest.mark.asyncio
async def test_get_or_create_after_session_gc_creates_new_session() -> None:
    """TTL 回收后再来消息: 新会话正常创建 (锁注册表自排空不影响后续取锁)。

    纯内存模式 (不传 db_path): 带持久化时 _gc_expired 的删库是异步 best-effort,
    重新 get_or_create 可能先从库 hydrate 回原 session_id (R5 语义), 与本测试
    关注的锁复用行为无关。
    """
    mgr = SessionManager({"session_ttl_seconds": 1})
    msg = ISACMessage(
        msg_id="m1", platform="webchat", timestamp=0, user_id="u1", user_name="u1", content="hi"
    )
    s1 = await mgr.get_or_create(msg, AGENT_ID)
    s1.last_active -= 10  # 人为过期
    mgr._gc_expired()
    assert mgr._sessions == {}
    s2 = await mgr.get_or_create(msg, AGENT_ID)
    assert s2.session_id != s1.session_id
    assert mgr._key_locks == {}
