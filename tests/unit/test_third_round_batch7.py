"""第三轮审查修复批 7 回归测试 (Fix-130~137: 剩余 Minor 清零)。

- Fix-130: SubAgentSupervisor._runs 内存索引封顶, 超限只淘汰最旧**终态** run (活跃不淘)。
- Fix-131: 主动任务生产者去重标记表 LRU 封顶 (_bound_marker)。
- Fix-132: event_store append 用 INSERT...RETURNING 原子取回 seq, 消除回读竞态。
- Fix-133: upload 安装 zip_b64 体积封顶 (对齐 URL 安装 MAX_PLUGIN_DOWNLOAD_BYTES)。
- Fix-134: audit.ndjson 超上限滚动轮转 (编号备份)。
- Fix-135: 隔离插件 reload/uninstall 经 _cached_path_for 取真实路径 (含 _iso_hosts)。
- Fix-136: DenyGuard 拒绝账本 LRU 封顶 + 事件流惰性重建, 逐出不破坏单调拒绝。
- Fix-137: 反应式门控移除死代码空闲退避判定 (不再因空闲连击 DELAY 合法回复)。
"""

from __future__ import annotations

import asyncio
import base64

import pytest

from isac.channel.model import ISACMessage
from isac.core.types import GatingContext
from isac.gateway.models import Session
from isac.gating.system import GatingSystem
from isac.gating.types import GateKind

# ── Fix-130: subagent _runs 封顶 ────────────────────────────────


@pytest.mark.asyncio
async def test_subagent_runs_pruned_to_cap_only_terminal() -> None:
    from isac.runtime.subagent.models import (
        TERMINAL_STATUSES,
        SubAgentPolicy,
        SubAgentResult,
        SubAgentTask,
    )
    from isac.runtime.subagent.supervisor import SubAgentSupervisor

    async def _runner(task: SubAgentTask) -> SubAgentResult:
        return SubAgentResult(task_id=task.task_id, status="succeeded", summary="ok")

    supervisor = SubAgentSupervisor(runner_factory=_runner, max_tracked_runs=5)

    def _task(task_id: str) -> SubAgentTask:
        return SubAgentTask(
            task_id=task_id, parent_agent_id="p", session_id="s1",
            trace_id="tr", objective="o", policy=SubAgentPolicy(timeout_seconds=60),
        )

    # 提交 12 个任务, 等待全部到终态
    for i in range(12):
        await supervisor.submit(_task(f"t{i}"))
    for _ in range(200):
        runs = list(supervisor._runs.values())  # noqa: SLF001
        if runs and all(r.status in TERMINAL_STATUSES for r in runs):
            break
        await asyncio.sleep(0.01)

    # 内存索引被封顶, 且保留的都是终态 run (活跃 run 不会被淘汰)
    assert len(supervisor._runs) <= 5  # noqa: SLF001
    assert all(r.status in TERMINAL_STATUSES for r in supervisor._runs.values())  # noqa: SLF001


@pytest.mark.asyncio
async def test_subagent_active_run_never_pruned() -> None:
    """有活跃 (running) run 时, 即便超限也不淘汰活跃 run。"""
    from isac.runtime.subagent.models import SubAgentPolicy, SubAgentResult, SubAgentTask
    from isac.runtime.subagent.supervisor import SubAgentSupervisor

    release = asyncio.Event()

    async def _runner(task: SubAgentTask) -> SubAgentResult:
        if task.task_id == "active":
            await release.wait()  # 挂住, 保持 running
        return SubAgentResult(task_id=task.task_id, status="succeeded", summary="ok")

    supervisor = SubAgentSupervisor(runner_factory=_runner, max_tracked_runs=2)

    def _task(task_id: str) -> SubAgentTask:
        return SubAgentTask(
            task_id=task_id, parent_agent_id="p", session_id="s1",
            trace_id="tr", objective="o", policy=SubAgentPolicy(timeout_seconds=60),
        )

    await supervisor.submit(_task("active"))
    await asyncio.sleep(0.02)  # 让 active 进入 running
    for i in range(5):
        await supervisor.submit(_task(f"done{i}"))
    for _ in range(200):
        done = [r for r in supervisor._runs.values() if r.status != "running"]  # noqa: SLF001
        if len(done) >= 5:
            break
        await asyncio.sleep(0.01)
    # 活跃 run 仍在索引中 (未被淘汰)
    assert "active" in supervisor._runs  # noqa: SLF001
    release.set()


# ── Fix-131: 生产者去重标记表封顶 ───────────────────────────────


def test_bound_marker_caps_and_keeps_touched() -> None:
    from isac.runtime.conversation.producer import _bound_marker

    marker: dict[str, float] = {}
    for i in range(10):
        marker[f"s{i}"] = float(i)
        _bound_marker(marker, f"s{i}", cap=5)
    # 封顶到 5, 且最近触及的键保留
    assert len(marker) == 5
    assert "s9" in marker
    # 最旧的被淘汰
    assert "s0" not in marker


def test_bound_marker_touch_moves_recent_to_end() -> None:
    from isac.runtime.conversation.producer import _bound_marker

    marker = {"a": 1.0, "b": 2.0, "c": 3.0}
    # 触及 a → a 移到末尾, 超 cap 时淘汰的是 b 而非 a
    _bound_marker(marker, "a", cap=3)
    marker["d"] = 4.0
    _bound_marker(marker, "d", cap=3)
    assert "a" in marker  # 最近触及, 未被淘汰
    assert "b" not in marker  # 最旧, 被淘汰


# ── Fix-132: event_store RETURNING 原子 seq ─────────────────────


@pytest.mark.asyncio
async def test_event_store_concurrent_append_unique_seq(tmp_path) -> None:
    """同分区并发 append 各自拿到唯一且连续的 seq (RETURNING 消除回读竞态)。"""
    from isac.session.event_store import SessionEventStore
    from isac.session.models import EVENT_USER_MESSAGE, SessionEvent

    store = SessionEventStore(str(tmp_path / "ev.db"))
    await store.start()
    try:
        key = "agent:webchat:user:u1"

        async def _append(i: int) -> int:
            return await store.append(
                SessionEvent(session_key=key, event_type=EVENT_USER_MESSAGE,
                             timestamp=1, payload={"content": f"m{i}"})
            )

        seqs = await asyncio.gather(*(_append(i) for i in range(20)))
        await store.flush()
        assert sorted(seqs) == list(range(1, 21))  # 唯一且连续
        assert len(set(seqs)) == 20
    finally:
        await store.stop()


# ── Fix-133: zip_b64 上传体积封顶 ───────────────────────────────


@pytest.mark.asyncio
async def test_zip_b64_oversized_rejected(tmp_path) -> None:
    from isac.plugin.runtime.installer import MAX_PLUGIN_DOWNLOAD_BYTES, PluginInstaller

    installer = PluginInstaller(tmp_path)
    # 构造解码后远超上限的 base64 (用重复字节, 不必是合法 zip —— 预检在解码前拒绝)
    oversized = base64.b64encode(b"\x00" * (MAX_PLUGIN_DOWNLOAD_BYTES + 1024)).decode()
    with pytest.raises(ValueError, match="过大"):
        await installer._write_b64_temp(oversized)  # noqa: SLF001


@pytest.mark.asyncio
async def test_zip_b64_normal_size_accepted(tmp_path) -> None:
    from isac.plugin.runtime.installer import PluginInstaller

    installer = PluginInstaller(tmp_path)
    small = base64.b64encode(b"PK\x03\x04tiny").decode()
    zip_path, owning_tmp = await installer._write_b64_temp(small)  # noqa: SLF001
    try:
        assert zip_path.exists()
        assert zip_path.read_bytes() == b"PK\x03\x04tiny"
    finally:
        import shutil

        shutil.rmtree(owning_tmp, ignore_errors=True)


# ── Fix-134: audit.ndjson 轮转 ──────────────────────────────────


@pytest.mark.asyncio
async def test_audit_log_rotates_when_oversized(tmp_path) -> None:
    from isac.control.audit import AuditLog

    log_path = tmp_path / "audit.ndjson"
    # 极小上限强制触发轮转
    audit = AuditLog(log_path=log_path, max_bytes=200, backup_count=2)
    for i in range(20):
        await audit.record(actor="u", method="POST", path="/x", action=f"a{i}", target="t")
    # 主文件存在且未超上限太多, 且至少产生了一个编号备份
    assert log_path.exists()
    backups = [p for p in tmp_path.glob("audit.ndjson.*")]
    assert backups, "应产生编号备份文件"


@pytest.mark.asyncio
async def test_audit_log_no_rotation_under_limit(tmp_path) -> None:
    from isac.control.audit import AuditLog

    log_path = tmp_path / "audit.ndjson"
    audit = AuditLog(log_path=log_path, max_bytes=10 * 1024 * 1024)
    for i in range(3):
        await audit.record(actor="u", method="POST", path="/x", action=f"a{i}")
    assert log_path.exists()
    assert not list(tmp_path.glob("audit.ndjson.*"))  # 未超限, 无备份


# ── Fix-135: 隔离插件真实路径解析 ───────────────────────────────


def test_cached_path_for_isolated_plugin() -> None:
    from pathlib import Path

    from isac.plugin.runtime.manager import PluginManager

    manager = PluginManager(config={})
    # 注入一个带 plugin_path 的假隔离宿主 (隔离插件不在 _loaded)
    manager._iso_hosts["iso_plugin"] = _FakeIsoHost("/real/dir/iso_plugin")  # noqa: SLF001
    manager._plugins_dir = Path("/plugins")  # noqa: SLF001

    # 隔离插件: 从 iso host 的 plugin_path 解析, 而非 plugins_dir/name
    assert manager._cached_path_for("iso_plugin") == Path("/real/dir/iso_plugin")  # noqa: SLF001
    # 未知插件: 返回 None (调用方回退 plugins_dir/name)
    assert manager._cached_path_for("nonexistent") is None  # noqa: SLF001


def test_cached_path_for_host_loaded_plugin() -> None:
    from pathlib import Path

    from isac.plugin.runtime.manager import PluginManager

    manager = PluginManager(config={})
    manager._loaded["host_plugin"] = _FakeLoadedPlugin("/real/dir/host_plugin")  # noqa: SLF001
    assert manager._cached_path_for("host_plugin") == Path("/real/dir/host_plugin")  # noqa: SLF001


class _FakeIsoHost:
    def __init__(self, path: str) -> None:
        self._path = path

    @property
    def plugin_path(self) -> str | None:
        return self._path


class _FakeLoadedPlugin:
    def __init__(self, path: str) -> None:
        self.path = path


# ── Fix-136: DenyGuard LRU + 惰性重建 ───────────────────────────


class _FakeDenialEvent:
    def __init__(self, seq: int, tool_name: str) -> None:
        self.seq = seq
        self.event_type = "tool.outcome"
        self.payload = {"tool_name": tool_name, "outcome": "DENIED"}


class _FakeDenialStore:
    """按 session_key 提供 DENIED 事件的假存储 (fetch 分页接口)。"""

    def __init__(self, denials: dict[str, list[str]]) -> None:
        self._denials = denials
        self.fetch_calls: list[str] = []

    async def fetch(self, session_key: str, after_seq: int = 0, limit: int = 1000):
        self.fetch_calls.append(session_key)
        tools = self._denials.get(session_key, [])
        events = [_FakeDenialEvent(i + 1, t) for i, t in enumerate(tools)]
        return [e for e in events if e.seq > after_seq][:limit]


@pytest.mark.asyncio
async def test_deny_guard_lru_evicts_and_lazy_restores() -> None:
    from isac.agent.tools.guard import DenyGuard

    store = _FakeDenialStore({"sess_old": ["bash"], "sess_new": ["rm"]})
    guard = DenyGuard(max_sessions=1)
    guard.bind_store(store)

    guard.register_denial("sess_old", "bash")
    guard.register_denial("sess_new", "rm")  # 超上限, sess_old 被逐出
    assert "sess_old" not in guard._denials  # noqa: SLF001

    # 对被逐出的会话 is_denied → 从事件流惰性重建, 单调拒绝不翻回
    assert await guard.is_denied("sess_old", "bash") is True
    assert await guard.is_denied("sess_new", "rm") is True
    assert await guard.is_denied("sess_old", "never") is False


@pytest.mark.asyncio
async def test_deny_guard_no_eviction_without_store() -> None:
    """未绑定事件存储时不逐出 (无持久化可重建, 绝不丢拒绝)。"""
    from isac.agent.tools.guard import DenyGuard

    guard = DenyGuard(max_sessions=1)  # 不 bind_store
    guard.register_denial("s1", "bash")
    guard.register_denial("s2", "rm")
    # 未绑定存储 → 不逐出, 两者都在
    assert await guard.is_denied("s1", "bash") is True
    assert await guard.is_denied("s2", "rm") is True


@pytest.mark.asyncio
async def test_deny_guard_lazy_restore_caches_empty() -> None:
    """无拒绝的会话惰性重建后缓存空集, 后续 is_denied 走内存命中不重复扫 store。"""
    from isac.agent.tools.guard import DenyGuard

    store = _FakeDenialStore({})  # 无任何拒绝
    guard = DenyGuard(max_sessions=10)
    guard.bind_store(store)

    assert await guard.is_denied("sess_x", "bash") is False
    calls_after_first = len(store.fetch_calls)
    assert await guard.is_denied("sess_x", "bash") is False
    # 第二次走缓存, 不再触发 store.fetch
    assert len(store.fetch_calls) == calls_after_first


# ── Fix-137: 移除死代码空闲退避判定 ─────────────────────────────


def _group_context() -> GatingContext:
    msg = ISACMessage(
        msg_id="m1", platform="webchat", timestamp=0,
        user_id="u1", user_name="u1", group_id="g1", content="帮我查一下天气",
    )
    session = Session(session_id="s1", user_id="u1", agent_id="a1",
                      platform="webchat", group_id="g1", is_group=True)
    return GatingContext(session=session, user_profile=None, current_message=msg,
                         is_private=False, has_at=False, has_mention=False)


@pytest.mark.asyncio
async def test_idle_backoff_no_longer_delays_reactive_reply() -> None:
    """Fix-137: 即便会话累计了空闲连击 (remaining_seconds>0), 评分达标的群聊消息
    仍 TRIGGER —— 反应式门控不再经空闲退避 DELAY 合法回复 (该判定此前恒为死代码)。"""
    gating = GatingSystem(config={"reply_necessity_threshold": 0})
    ctx = _group_context()
    backoff = gating.get_idle_backoff(ctx.session.session_id)
    for _ in range(5):
        backoff.record_idle()
    assert backoff.remaining_seconds > 0  # 空闲连击确实存在

    decision = await gating.evaluate([ctx.current_message], ctx)
    assert decision.kind == GateKind.TRIGGER  # 不是 DELAY


@pytest.mark.asyncio
async def test_idle_backoff_controller_still_isolated_per_session() -> None:
    """组件保留: get_idle_backoff 仍按会话隔离 (既有隔离语义不变)。"""
    gating = GatingSystem()
    a = gating.get_idle_backoff("sess_a")
    b = gating.get_idle_backoff("sess_b")
    assert a is not b
    assert gating.get_idle_backoff("sess_a") is a
