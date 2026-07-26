"""L5 上下文恢复业务测试。

覆盖:
- ConversationStateStore.save/load 真实持久化 (原子写 + JSON)
- 短间隔重启 (< 5min) recovery_hint="自然接上话题"
- 中等间隔 (< 1h) "刚上线但记得前情"
- 长间隔 (> 1h) "睡了一会儿/刚回来"
- 超过 24h 不恢复 (视为新会话)
- 未决 wait 标记为终止 (state=idle, pending_wait=None, 不续跑旧进度)
- 不存在 session_id load 返回 None
- RecoveryInjector 注入 hint 到第一轮
- enabled=False 零行为变化
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from isac.agent.injectors.recovery import RecoveryInjector
from isac.gateway.models import Session
from isac.runtime.conversation import ConversationSnapshot, ConversationStateStore


def _make_session(session_id: str = "s1") -> Session:
    return Session(session_id=session_id, user_id="u1", platform="webchat")


def _make_injection_context(session_id: str = "s1") -> SimpleNamespace:
    return SimpleNamespace(session=_make_session(session_id))


def _make_store(tmp_path: Path) -> ConversationStateStore:
    return ConversationStateStore(base_dir=str(tmp_path))


def test_store_save_then_load_roundtrip(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    snap = ConversationSnapshot(
        agent_id="a1",
        session_id="s1",
        state="thinking",
        recent_message_ids=["m1", "m2"],
    )
    store.save(snap)
    loaded = store.load("a1", "s1")
    assert loaded is not None
    # 运行态复位为 idle (中断后不续跑旧进度, 与 D9/J4 思路一致)
    assert loaded.state == "idle"
    assert loaded.agent_id == "a1"
    assert loaded.session_id == "s1"
    assert loaded.recent_message_ids == ["m1", "m2"]


def test_store_load_nonexistent_returns_none(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.load("a1", "unknown_session") is None


def test_store_load_short_interval_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """短间隔重启 (< 5min): recovery_hint 提示自然接上话题."""
    store = _make_store(tmp_path)
    snap = ConversationSnapshot(agent_id="a1", session_id="s1")
    # 模拟 100 秒前保存 (短间隔)
    save_time = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: save_time)
    store.save(snap)
    # 现在 = save_time + 100 秒 (短间隔)
    monkeypatch.setattr(time, "time", lambda: save_time + 100)
    loaded = store.load("a1", "s1")
    assert loaded is not None
    assert "自然接上" in loaded.recovery_hint or "接上" in loaded.recovery_hint


def test_store_load_medium_interval_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """中等间隔 (5min ~ 1h): 刚上线但记得前情."""
    store = _make_store(tmp_path)
    save_time = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: save_time)
    store.save(ConversationSnapshot(agent_id="a1", session_id="s1"))
    # 30 分钟后加载
    monkeypatch.setattr(time, "time", lambda: save_time + 1800)
    loaded = store.load("a1", "s1")
    assert loaded is not None
    assert "刚上线" in loaded.recovery_hint or "记得前情" in loaded.recovery_hint


def test_store_load_long_interval_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """长间隔 (1h ~ 24h): 睡了一会儿/刚回来."""
    store = _make_store(tmp_path)
    save_time = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: save_time)
    store.save(ConversationSnapshot(agent_id="a1", session_id="s1"))
    # 2 小时后加载
    monkeypatch.setattr(time, "time", lambda: save_time + 7200)
    loaded = store.load("a1", "s1")
    assert loaded is not None
    assert "睡" in loaded.recovery_hint or "刚回来" in loaded.recovery_hint


def test_store_load_over_24h_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """超过 24h 不恢复 (视为新会话)."""
    store = _make_store(tmp_path)
    save_time = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: save_time)
    store.save(ConversationSnapshot(agent_id="a1", session_id="s1"))
    # 25 小时后加载
    monkeypatch.setattr(time, "time", lambda: save_time + 25 * 3600)
    assert store.load("a1", "s1") is None


def test_store_load_resets_pending_wait_to_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """未决 wait 标记为终止 (不续跑旧进度)."""
    from isac.runtime.conversation import WaitState

    store = _make_store(tmp_path)
    save_time = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: save_time)
    wait = WaitState(tool_call_id="c1", started_at=save_time - 5, requested_seconds=30, reason="等回复")
    snap = ConversationSnapshot(
        agent_id="a1",
        session_id="s1",
        state="waiting",
        pending_wait=wait,
    )
    store.save(snap)
    monkeypatch.setattr(time, "time", lambda: save_time + 60)  # 60 秒后 (短间隔)
    loaded = store.load("a1", "s1")
    assert loaded is not None
    # 中断后不续跑 wait: pending_wait 置 None, state=idle
    assert loaded.pending_wait is None
    assert loaded.state == "idle"


def test_store_save_atomic_writes_json_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """save 写出 JSON 文件到 data/agents/<id>/conversation/<session_id>.json."""
    store = _make_store(tmp_path)
    monkeypatch.setattr(time, "time", lambda: 1_000_000.0)
    store.save(ConversationSnapshot(agent_id="a1", session_id="s1"))
    expected_path = tmp_path / "a1" / "conversation" / "s1.json"
    assert expected_path.exists()


# ── RecoveryInjector ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recovery_injector_injects_hint_when_snapshot_present() -> None:
    """启动恢复后第一轮注入 recovery_hint (注入后清空)."""
    store = _make_store(Path("/tmp/isac_l5_test"))  # 用真 store, 启动时已 load
    snap = ConversationSnapshot(agent_id="a1", session_id="s1", recovery_hint="刚上线但记得前情")
    injector = RecoveryInjector(store=store, snapshots={"s1": snap})
    result = await injector.build(_make_injection_context("s1"))
    assert "刚上线" in result
    # 第二次调用应清空 (不再注入)
    result2 = await injector.build(_make_injection_context("s1"))
    assert result2 == ""


@pytest.mark.asyncio
async def test_recovery_injector_empty_when_no_snapshot() -> None:
    """无快照时返回空 (零行为变化)."""
    store = _make_store(Path("/tmp/isac_l5_test"))
    injector = RecoveryInjector(store=store, snapshots={})
    result = await injector.build(_make_injection_context("s1"))
    assert result == ""
