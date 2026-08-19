"""阶段3-2 (M4) 出站投递保障测试: _send_reply 有界重试 + 死信环。

验收:
- 首次成功 → 只发一次, 无死信;
- 瞬时失败后成功 → 重试后送达;
- 全部失败 / 适配器抛异常 → 重试耗尽后记入死信环 (不静默丢);
- OutboundDeadLetter 有界 (maxlen) + recent() 可查。
"""

from __future__ import annotations

import asyncio

import pytest

from isac.channel.model import ISACMessage
from isac.channel.registry import ChannelRegistry
from isac.outbound import OutboundDeadLetter, _send_reply


class _ScriptedAdapter:
    """按脚本返回 send 结果 (bool) 或抛异常的 fake 适配器。"""

    platform_name = "fake"

    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.send_calls = 0

    async def send(self, reply: ISACMessage) -> bool:
        self.send_calls += 1
        if not self._results:
            return True
        r = self._results.pop(0)
        if isinstance(r, Exception):
            raise r
        return bool(r)


def _registry(adapter: _ScriptedAdapter) -> ChannelRegistry:
    registry = ChannelRegistry()
    registry.register(adapter)
    return registry


def _incoming() -> ISACMessage:
    return ISACMessage(
        msg_id="m1", platform="fake", timestamp=0, user_id="u1",
        user_name="U", group_id=None, session_id="s1", content="hi",
    )


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _instant(delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


@pytest.mark.asyncio
async def test_send_success_first_attempt(no_sleep: None) -> None:
    adapter = _ScriptedAdapter([True])
    dl = OutboundDeadLetter()
    await _send_reply(_registry(adapter), _incoming(), "reply", "a1", dead_letter=dl)
    assert adapter.send_calls == 1
    assert len(dl) == 0


@pytest.mark.asyncio
async def test_send_retries_then_succeeds(no_sleep: None) -> None:
    adapter = _ScriptedAdapter([False, False, True])  # 前两次失败, 第三次成功
    dl = OutboundDeadLetter()
    await _send_reply(_registry(adapter), _incoming(), "reply", "a1", dead_letter=dl)
    assert adapter.send_calls == 3
    assert len(dl) == 0  # 最终送达, 不进死信


@pytest.mark.asyncio
async def test_send_all_fail_records_dead_letter(no_sleep: None) -> None:
    adapter = _ScriptedAdapter([False, False, False])
    dl = OutboundDeadLetter()
    await _send_reply(_registry(adapter), _incoming(), "reply", "a1", dead_letter=dl)
    assert adapter.send_calls == 3  # 重试耗尽 (默认 3 次)
    assert len(dl) == 1
    entry = dl.recent()[0]
    assert entry["platform"] == "fake"
    assert entry["agent_id"] == "a1"
    assert entry["attempts"] == 3


@pytest.mark.asyncio
async def test_send_exception_treated_as_failure(no_sleep: None) -> None:
    adapter = _ScriptedAdapter([RuntimeError("boom"), RuntimeError("boom"), RuntimeError("boom")])
    dl = OutboundDeadLetter()
    await _send_reply(_registry(adapter), _incoming(), "reply", "a1", dead_letter=dl)
    assert adapter.send_calls == 3
    assert len(dl) == 1


@pytest.mark.asyncio
async def test_missing_adapter_no_dead_letter(no_sleep: None) -> None:
    """平台无适配器 → 记 warning 直接返回, 不进死信 (非'发送失败'语义)。"""
    dl = OutboundDeadLetter()
    await _send_reply(ChannelRegistry(), _incoming(), "reply", "a1", dead_letter=dl)
    assert len(dl) == 0


# ── OutboundDeadLetter 有界环 ──────────────────────────────────


def test_dead_letter_bounded_and_recent() -> None:
    dl = OutboundDeadLetter(maxlen=3)
    for i in range(5):
        dl.record(platform="fake", agent_id="a", session_id=f"s{i}", attempts=3)
    assert len(dl) == 3  # maxlen 约束
    recent = dl.recent()
    # 保留最新 3 条 (s2/s3/s4), 最旧 s0/s1 被挤出
    assert [e["session_id"] for e in recent] == ["s2", "s3", "s4"]
