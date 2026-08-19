"""U1 事件溯源会话内核专项测试 (SessionEventStore + SessionHistoryDeriver)。

覆盖 U1 验收: 重放无损 / 压缩溯源 (source_seqs + 摘要≥原文拒绝) / torn-tail 修复 /
未知事件类型拒绝重建 / 滑动窗口 (最近 N 轮 + budget 感知截断, memory 关闭仍可用)。
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from isac.session.event_store import SessionEventStore
from isac.session.history import SessionHistoryDeriver, UnknownSessionEventError, estimate_tokens
from isac.session.models import (
    EVENT_TOOL_CALLED,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_COMPRESSED,
    EVENT_USER_MESSAGE,
    SessionEvent,
)

KEY = "agent_a:webchat:group:G1"


async def _started_store(tmp_path: Path) -> SessionEventStore:
    store = SessionEventStore(str(tmp_path / "session_events.db"))
    await store.start()
    return store


def _ev(event_type: str, content: str = "", seq: int = 0, **payload) -> SessionEvent:
    p: dict = dict(payload)
    if content:
        p.setdefault("content", content)
    return SessionEvent(session_key=KEY, event_type=event_type, timestamp=1, payload=p, seq=seq)


# ── SessionEventStore: 追加 / seq / 重放 ─────────────────────


@pytest.mark.asyncio
async def test_append_assigns_monotonic_seq(tmp_path: Path) -> None:
    store = await _started_store(tmp_path)
    try:
        s1 = await store.append(_ev(EVENT_USER_MESSAGE, "你好"))
        s2 = await store.append(_ev(EVENT_TURN_COMPLETED, "你好, 有什么可以帮你"))
        s3 = await store.append(_ev(EVENT_USER_MESSAGE, "天气"))
        assert (s1, s2, s3) == (1, 2, 3)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_append_rejects_overwrite_existing_seq(tmp_path: Path) -> None:
    """append-only 后门封堵回归: 显式 seq 撞既有 (session_key, seq) 必须报错, 不得静默覆盖。

    2026-08-19: 原 INSERT OR REPLACE 允许对既有事件改写, 违背"事件只追加不涂改"。
    封堵后同 seq 追加触发主键冲突 IntegrityError; 原事件内容保持不变。
    """
    store = await _started_store(tmp_path)
    try:
        await store.append(_ev(EVENT_USER_MESSAGE, "原始内容", seq=1))
        with pytest.raises(sqlite3.IntegrityError):
            await store.append(_ev(EVENT_USER_MESSAGE, "企图覆盖", seq=1))
        await store.flush()
        events = await store.fetch(KEY)
        assert len(events) == 1
        assert events[0].payload["content"] == "原始内容"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_replay_lossless_after_reopen(tmp_path: Path) -> None:
    """重放无损: 写入→关闭→重新打开→fetch 完整还原事件序列。"""
    db = str(tmp_path / "session_events.db")
    store = SessionEventStore(db)
    await store.start()
    await store.append(_ev(EVENT_USER_MESSAGE, "第一句"))
    await store.append(_ev(EVENT_TURN_COMPLETED, "回复一"))
    await store.append(_ev(EVENT_USER_MESSAGE, "第二句"))
    await store.flush()
    await store.stop()

    # 重新打开 (模拟重启) → 事件完整
    store2 = SessionEventStore(db)
    await store2.start()
    try:
        events = await store2.fetch(KEY)
        assert [e.event_type for e in events] == [
            EVENT_USER_MESSAGE, EVENT_TURN_COMPLETED, EVENT_USER_MESSAGE,
        ]
        assert [e.payload["content"] for e in events] == ["第一句", "回复一", "第二句"]
        assert [e.seq for e in events] == [1, 2, 3]
    finally:
        await store2.stop()


@pytest.mark.asyncio
async def test_concurrent_append_no_seq_collision(tmp_path: Path) -> None:
    """并发追加 seq 不冲突不丢事件 (原子 INSERT...SELECT 分配)。"""
    store = await _started_store(tmp_path)
    try:
        await asyncio.gather(*(store.append(_ev(EVENT_USER_MESSAGE, f"m{i}")) for i in range(30)))
        events = await store.fetch(KEY, limit=100)
        seqs = [e.seq for e in events]
        assert sorted(seqs) == list(range(1, 31))  # 无重复无缺口
        assert len(set(seqs)) == 30
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_fetch_isolated_by_session_key(tmp_path: Path) -> None:
    store = await _started_store(tmp_path)
    try:
        await store.append(_ev(EVENT_USER_MESSAGE, "A 的消息"))
        other = SessionEvent(session_key="agent_b:qq:user:U9", event_type=EVENT_USER_MESSAGE,
                             timestamp=1, payload={"content": "B 的消息"})
        await store.append(other)
        a_events = await store.fetch(KEY)
        assert [e.payload["content"] for e in a_events] == ["A 的消息"]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_sanitize_strips_sensitive_payload_keys(tmp_path: Path) -> None:
    store = await _started_store(tmp_path)
    try:
        await store.append(_ev(EVENT_USER_MESSAGE, "x", api_key="sk-secret", token="t"))
        events = await store.fetch(KEY)
        assert "api_key" not in events[0].payload
        assert "token" not in events[0].payload
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_unstarted_store_safe_degrade(tmp_path: Path) -> None:
    store = SessionEventStore(str(tmp_path / "x.db"))  # 未 start
    assert await store.append(_ev(EVENT_USER_MESSAGE, "x")) == 0
    assert await store.fetch(KEY) == []
    await store.flush()  # 不 raise


# ── torn-tail 修复 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repair_torn_tail_orphan_tool_call(tmp_path: Path) -> None:
    """孤儿 tool.called (无 outcome) → 追加 OUTCOME_UNKNOWN, 不猜结果。"""
    store = await _started_store(tmp_path)
    try:
        await store.append(_ev(EVENT_TOOL_CALLED, tool_name="bash"))
        await store.append(_ev(EVENT_TOOL_CALLED, tool_name="read_file"))
        # 只有第一个有 outcome
        from isac.session.models import EVENT_TOOL_OUTCOME
        await store.append(_ev(EVENT_TOOL_OUTCOME, outcome="ok"))
        repaired = await store.repair_torn_tail(KEY)
        assert repaired == 1  # 一个孤儿被修复
        events = await store.fetch(KEY)
        outcomes = [e for e in events if e.event_type == EVENT_TOOL_OUTCOME]
        assert any(e.payload.get("outcome") == "OUTCOME_UNKNOWN" for e in outcomes)
    finally:
        await store.stop()


# ── SessionHistoryDeriver: 折叠 / 压缩 / 窗口 / 未知事件 ─────


def test_fold_user_assistant_sequence() -> None:
    d = SessionHistoryDeriver()
    events = [
        _ev(EVENT_USER_MESSAGE, "你好", seq=1),
        _ev(EVENT_TURN_COMPLETED, "你好呀", seq=2),
        _ev(EVENT_USER_MESSAGE, "再见", seq=3),
        _ev(EVENT_TURN_COMPLETED, "拜拜", seq=4),
    ]
    msgs = d.fold(events)
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "你好"), ("assistant", "你好呀"), ("user", "再见"), ("assistant", "拜拜"),
    ]


def test_fold_applies_compression_source_seqs() -> None:
    """压缩溯源: turn.compressed 的 source_seqs 引用的原始事件被摘要替代。"""
    d = SessionHistoryDeriver()
    events = [
        _ev(EVENT_USER_MESSAGE, "很久以前的问题", seq=1),
        _ev(EVENT_TURN_COMPLETED, "很久以前的回答", seq=2),
        _ev(EVENT_TURN_COMPRESSED, summary="摘要: 用户问过历史问题", seq=3, source_seqs=[1, 2]),
        _ev(EVENT_USER_MESSAGE, "最近的问题", seq=4),
        _ev(EVENT_TURN_COMPLETED, "最近的回答", seq=5),
    ]
    msgs = d.fold(events)
    contents = [m["content"] for m in msgs]
    assert "很久以前的问题" not in contents  # 被压缩掉
    assert "很久以前的回答" not in contents
    assert "摘要: 用户问过历史问题" in contents  # 摘要替代
    assert contents[-2:] == ["最近的问题", "最近的回答"]


def test_fold_rejects_unknown_event_type() -> None:
    """未知事件类型默认拒绝重建。"""
    d = SessionHistoryDeriver()
    events = [
        _ev(EVENT_USER_MESSAGE, "ok", seq=1),
        _ev("weird.future.event", seq=2),
    ]
    with pytest.raises(UnknownSessionEventError):
        d.fold(events)


def test_derive_window_sliding_keeps_recent_turns() -> None:
    """滑动窗口: 只保留最近 N 轮 (window_turns=2 → 最近 4 条)。"""
    d = SessionHistoryDeriver(window_turns=2)
    events = []
    seq = 0
    for i in range(5):  # 5 轮
        seq += 1
        events.append(_ev(EVENT_USER_MESSAGE, f"问{i}", seq=seq))
        seq += 1
        events.append(_ev(EVENT_TURN_COMPLETED, f"答{i}", seq=seq))
    msgs = d.derive_window(events)
    assert len(msgs) == 4  # 2 轮 = 4 条
    # 保留的是最近的 (问3/答3/问4/答4)
    assert [m["content"] for m in msgs] == ["问3", "答3", "问4", "答4"]


def test_derive_window_budget_truncation() -> None:
    """budget 感知截断: 从最旧丢弃, 至少保留最近一条。"""
    d = SessionHistoryDeriver(window_turns=100, budget_tokens=20)
    events = []
    for i in range(6):
        events.append(_ev(EVENT_USER_MESSAGE, "长内容" * 20, seq=i + 1))  # 每条 ~60 字符 ~30 token
    msgs = d.derive_window(events)
    total = sum(estimate_tokens(m["content"]) for m in msgs)
    assert total <= 20 or len(msgs) == 1  # 预算内, 或只剩一条
    assert len(msgs) >= 1


def test_derive_window_memory_off_still_works() -> None:
    """底线场景: memory 关闭 (无记忆检索) 时窗口派生仍可用 —— 派生只依赖事件流。"""
    d = SessionHistoryDeriver(window_turns=3)
    events = [
        _ev(EVENT_USER_MESSAGE, "a", seq=1),
        _ev(EVENT_TURN_COMPLETED, "b", seq=2),
    ]
    assert d.derive_window(events) == [
        {"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
    ]


def test_validate_compression_rejects_non_shrinking() -> None:
    """压缩溯源: 摘要不小于原文 → 拒绝提交。"""
    original = "这是需要被压缩的较长原文内容"
    assert SessionHistoryDeriver.validate_compression(original, "短摘要") is True
    assert SessionHistoryDeriver.validate_compression(original, original) is False  # 等大拒绝
    assert SessionHistoryDeriver.validate_compression(original, original + "更长") is False


def test_tool_events_not_in_history_window() -> None:
    """tool.* 事件不进聊天历史窗口 (仅审计/torn-tail 用)。"""
    d = SessionHistoryDeriver()
    events = [
        _ev(EVENT_USER_MESSAGE, "跑个命令", seq=1),
        _ev(EVENT_TOOL_CALLED, seq=2, tool_name="bash"),
        _ev(EVENT_TURN_COMPLETED, "跑完了", seq=3),
    ]
    msgs = d.fold(events)
    assert [m["content"] for m in msgs] == ["跑个命令", "跑完了"]


# ── 旧 sessions 迁移 + ignorable 白名单 ─────────────────────


def test_fold_skips_session_migrated_ignorable_event() -> None:
    """session.migrated 是 ignorable 事件: fold 安全跳过, 不拒绝不进历史。"""
    from isac.session.models import EVENT_SESSION_MIGRATED

    d = SessionHistoryDeriver()
    events = [
        _ev(EVENT_SESSION_MIGRATED, seq=1, legacy_session_id="sess_old"),
        _ev(EVENT_USER_MESSAGE, "你好", seq=2),
        _ev(EVENT_TURN_COMPLETED, "你好呀", seq=3),
    ]
    msgs = d.fold(events)
    assert [(m["role"], m["content"]) for m in msgs] == [("user", "你好"), ("assistant", "你好呀")]


@pytest.mark.asyncio
async def test_migrate_legacy_sessions_writes_marker_events(tmp_path: Path) -> None:
    """旧 sessions 表 → session.migrated 标记事件 (幂等, dry-run 不写)。"""
    import sqlite3

    from isac.session.migrate import migrate_legacy_sessions
    from isac.session.models import EVENT_SESSION_MIGRATED

    data_dir = tmp_path / "data"
    (data_dir / "gateway").mkdir(parents=True)
    legacy = sqlite3.connect(data_dir / "gateway" / "sessions.db")
    legacy.execute(
        "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, session_key TEXT NOT NULL, "
        "user_id TEXT, agent_id TEXT, platform TEXT, group_id TEXT, is_group INTEGER, "
        "created_at INTEGER, last_active INTEGER, state TEXT, "
        "platform_session_id TEXT DEFAULT '', user_ids TEXT DEFAULT '{}')"
    )
    legacy.execute(
        "INSERT INTO sessions VALUES ('sess_1', 'a:qq:group:G1', 'u1', 'a', 'qq', 'G1', 1, 100, 200, 'idle', '', '{}')"
    )
    legacy.execute(
        "INSERT INTO sessions VALUES ('sess_2', 'a:qq:user:U2', 'u2', 'a', 'qq', NULL, 0, 150, 250, 'idle', '', '{}')"
    )
    legacy.commit()
    legacy.close()

    # dry-run 只报告不写
    dry = await migrate_legacy_sessions(data_dir, dry_run=True)
    assert dry["migrated"] == 2 and dry["legacy_total"] == 2

    store_probe = SessionEventStore(str(data_dir / "gateway" / "session_events.db"))
    await store_probe.start()
    assert await store_probe.max_seq("a:qq:group:G1") == 0  # dry-run 未写
    await store_probe.stop()

    report = await migrate_legacy_sessions(data_dir)
    assert report["migrated"] == 2 and report["skipped_existing"] == 0

    store_probe = SessionEventStore(str(data_dir / "gateway" / "session_events.db"))
    await store_probe.start()
    events = await store_probe.fetch("a:qq:group:G1")
    assert len(events) == 1
    assert events[0].event_type == EVENT_SESSION_MIGRATED
    assert events[0].payload["legacy_session_id"] == "sess_1"
    assert events[0].timestamp == 200  # 取 last_active
    # 幂等: 已有事件的分区跳过
    report2 = await migrate_legacy_sessions(data_dir)
    assert report2["migrated"] == 0 and report2["skipped_existing"] == 2
    await store_probe.stop()


@pytest.mark.asyncio
async def test_migrate_legacy_sessions_missing_db_noop(tmp_path: Path) -> None:
    """旧库不存在 (新装环境) → 无需迁移, 不建事件库也不报错。"""
    from isac.session.migrate import migrate_legacy_sessions

    report = await migrate_legacy_sessions(tmp_path / "no_data_dir")
    assert report["legacy_total"] == 0 and report["migrated"] == 0
