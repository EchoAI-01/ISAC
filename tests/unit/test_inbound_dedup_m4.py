"""阶段3-2 (M4) 入站幂等去重测试: InboundDeduplicator + dispatch 入口接线。

验收: 重复投递 (同 platform+msg_id) 在 TTL 内只处理一次; 空 msg_id 不去重 (放行);
不同平台同 msg_id 不互相误伤; LRU 上限与 TTL 过期保证表不无界; dispatch 入口拦截
重复消息不进入处理链。
"""

from __future__ import annotations

import pytest

import isac.dispatch as dispatch_mod
from isac.channel.model import ISACMessage
from isac.dispatch import make_message_dispatcher
from isac.gateway.inbound_dedup import InboundDeduplicator
from isac.gateway.lock import SessionLockManager

# ── InboundDeduplicator 单元 ───────────────────────────────────


def test_first_seen_not_duplicate() -> None:
    d = InboundDeduplicator()
    assert d.is_duplicate("telegram", "m1") is False


def test_second_seen_is_duplicate() -> None:
    d = InboundDeduplicator()
    assert d.is_duplicate("telegram", "m1") is False
    assert d.is_duplicate("telegram", "m1") is True


def test_empty_msg_id_not_deduplicated() -> None:
    d = InboundDeduplicator()
    assert d.is_duplicate("telegram", "") is False
    assert d.is_duplicate("telegram", "") is False  # 空 id 恒放行, 不记表
    assert len(d) == 0


def test_different_platform_same_msg_id_isolated() -> None:
    d = InboundDeduplicator()
    assert d.is_duplicate("telegram", "m1") is False
    # 同 msg_id 但不同平台 → 不同键, 不误伤。
    assert d.is_duplicate("discord", "m1") is False
    assert d.is_duplicate("telegram", "m1") is True


def test_lru_cap_evicts_oldest() -> None:
    d = InboundDeduplicator(max_entries=2, ttl_seconds=600)
    d.is_duplicate("p", "a")
    d.is_duplicate("p", "b")
    d.is_duplicate("p", "c")  # 超限, 逐出最旧 "a"
    assert len(d) == 2
    # "b"/"c" 仍在表内仍判重; "a" 已被逐出 → 再次出现视为首见 (有界内存权衡)
    assert d.is_duplicate("p", "b") is True
    assert d.is_duplicate("p", "c") is True
    assert d.is_duplicate("p", "a") is False


def test_ttl_expiry_allows_reprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    import isac.gateway.inbound_dedup as mod

    fake_now = [1000.0]
    monkeypatch.setattr(mod.time, "time", lambda: fake_now[0])
    d = InboundDeduplicator(ttl_seconds=10)
    assert d.is_duplicate("p", "m1") is False
    assert d.is_duplicate("p", "m1") is True
    fake_now[0] += 20  # 超过 TTL
    assert d.is_duplicate("p", "m1") is False  # 过期后视为首见


# ── dispatch 入口接线: 重复消息不进处理链 ──────────────────────


class _NullRouter:
    async def route(self, message):  # noqa: ANN001
        return None


def _msg(msg_id: str) -> ISACMessage:
    return ISACMessage(
        msg_id=msg_id, platform="fake", timestamp=0, user_id="u1", user_name="U", content="hi"
    )


async def test_dispatch_entry_dedupes_same_message(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _counting(message: ISACMessage, **kwargs) -> None:  # noqa: ANN001
        calls.append(message.msg_id)

    monkeypatch.setattr(dispatch_mod, "process_message", _counting)
    metrics = _CountingMetrics()
    handle, drain = make_message_dispatcher(
        event_bus=object(), router=_NullRouter(), session_mgr=object(), user_mapper=object(),
        agent_manager=object(), channel_registry=object(), metrics=metrics,
        session_lock=SessionLockManager(), drain_timeout_seconds=1.0,
    )
    await handle(_msg("dup1"))
    await handle(_msg("dup1"))  # 重复投递 → 应被拦截
    await handle(_msg("other"))  # 不同 msg_id → 正常处理
    await drain()
    assert calls == ["dup1", "other"]
    # 重复消息记 dedicated 指标恰好一次
    assert metrics.counters.get("isac_messages_deduplicated_total") == 1


class _FakeCounter:
    def __init__(self) -> None:
        self.value = 0

    def inc(self) -> None:
        self.value += 1


class _CountingMetrics:
    def __init__(self) -> None:
        self._counters: dict[str, _FakeCounter] = {}

    def counter(self, name: str) -> _FakeCounter:
        if name not in self._counters:
            self._counters[name] = _FakeCounter()
        return self._counters[name]

    @property
    def counters(self) -> dict[str, int]:
        return {name: c.value for name, c in self._counters.items()}
