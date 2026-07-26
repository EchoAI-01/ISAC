"""M2 Agent Mesh 协作动作业务测试。

覆盖:
- MeshActionBroker.is_permitted: policy-None 拒绝; action 在 permissions 中允许; 不在拒绝
- notify/handoff/memory_query 真实调 bus.send + 返回 True (ACL 通过)
- memory_query 按 visible_memory_scopes 裁剪
- list_available 从 bus links 过滤可见对端
- 默认 deny-by-default 零行为变化
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from isac.runtime.bus import InterAgentBus, InterAgentLink, InterAgentMessage
from isac.runtime.mesh.actions import MeshActionBroker
from isac.runtime.mesh.models import MeshLinkPolicy, MeshMessageType


def _policy(permissions: list[str], **kw: Any) -> MeshLinkPolicy:
    """构造 MeshLinkPolicy, 默认空 permissions."""
    base: dict[str, Any] = {"permissions": permissions}
    base.update(kw)
    return MeshLinkPolicy(**base)  # type: ignore[arg-type]


def _make_bus() -> InterAgentBus:
    """构造内存级 InterAgentBus, 不注入 deliver (测试场景只看 send 是否被调用)."""
    return InterAgentBus()


# ── is_permitted ─────────────────────────────────────────────────


def test_is_permitted_rejects_none_policy() -> None:
    broker = MeshActionBroker()
    assert broker.is_permitted("notify", None) is False


def test_is_permitted_allows_action_in_permissions() -> None:
    broker = MeshActionBroker()
    policy = _policy(["notify", "handoff"])
    assert broker.is_permitted("notify", policy) is True
    assert broker.is_permitted("handoff", policy) is True


def test_is_permitted_rejects_action_not_in_permissions() -> None:
    broker = MeshActionBroker()
    policy = _policy(["notify"])
    assert broker.is_permitted("handoff", policy) is False
    assert broker.is_permitted("memory_query", policy) is False


# ── notify / handoff / memory_query ─────────────────────────────


@pytest.mark.asyncio
async def test_notify_sends_message_via_bus_when_permitted() -> None:
    """notify ACL 通过时经 bus.send 投递 NOTIFY 消息, 返回 True (bus 对 notify 不调 deliver)."""
    bus = _make_bus()
    bus.add_link(InterAgentLink(from_agent="a1", to_agent="a2", direction="both", enabled=True))
    sent: list[InterAgentMessage] = []
    bus.set_deliver(_make_deliver_capture(sent))
    broker = MeshActionBroker(bus)
    policy = _policy(["notify"])
    ok = await broker.notify("a1", "a2", "提醒用户喝水", policy)
    assert ok is True
    # bus.send 对 notify 类型不调 deliver (直接 return None), 但仍记日志 + 通过 ACL
    # 验证: 不抛 InterAgentLinkDeniedError (ACL 通过), 返回 True
    assert sent == []  # notify 不调 deliver (符合 bus 设计)


@pytest.mark.asyncio
async def test_notify_rejected_by_acl_returns_false() -> None:
    """notify ACL 不通过 (action 不在 permissions) 时不投递, 返回 False."""
    bus = _make_bus()
    sent: list[InterAgentMessage] = []
    bus.set_deliver(_make_deliver_capture(sent))
    broker = MeshActionBroker(bus)
    # policy 不含 notify
    policy = _policy(["handoff"])
    ok = await broker.notify("a1", "a2", "x", policy)
    assert ok is False
    assert sent == []


@pytest.mark.asyncio
async def test_handoff_sends_message_with_summary() -> None:
    """handoff ACL 通过时投递 HANDOFF 消息 + 会话摘要 (deliver 被调用, context.summary)."""
    bus = _make_bus()
    bus.add_link(InterAgentLink(from_agent="a1", to_agent="a2"))
    sent: list[InterAgentMessage] = []
    bus.set_deliver(_make_deliver_capture(sent))
    broker = MeshActionBroker(bus)
    policy = _policy(["handoff"])
    ok = await broker.handoff("a1", "a2", "用户在咨询天气", policy)
    assert ok is True
    assert len(sent) == 1
    assert sent[0].type == MeshMessageType.HANDOFF.value
    assert sent[0].context.get("summary") == "用户在咨询天气"


@pytest.mark.asyncio
async def test_memory_query_filters_by_visible_memory_scopes() -> None:
    """memory_query 按 visible_memory_scopes 裁剪可见范围 (context.filters)."""
    bus = _make_bus()
    bus.add_link(InterAgentLink(from_agent="a1", to_agent="a2"))
    sent: list[InterAgentMessage] = []
    bus.set_deliver(_make_deliver_capture(sent))
    broker = MeshActionBroker(bus)
    policy = _policy(
        ["memory_query"],
        visible_memory_scopes=["agent_private", "conversation"],
    )
    ok = await broker.memory_query("a1", "a2", "周末计划", policy)
    assert ok is True
    assert sent[0].type == MeshMessageType.MEMORY_QUERY.value
    # visible_memory_scopes 进 context.filters, 让接收方按 scope 裁剪
    assert sent[0].context.get("filters") == {"scopes": ["agent_private", "conversation"]}


@pytest.mark.asyncio
async def test_memory_query_rejected_without_permission() -> None:
    """memory_query 不在 permissions 时拒绝, 不投递."""
    bus = _make_bus()
    sent: list[InterAgentMessage] = []
    bus.set_deliver(_make_deliver_capture(sent))
    broker = MeshActionBroker(bus)
    policy = _policy(["notify"])  # 不含 memory_query
    ok = await broker.memory_query("a1", "a2", "x", policy)
    assert ok is False
    assert sent == []


# ── list_available ───────────────────────────────────────────────


def test_list_available_returns_linked_peers() -> None:
    """list_available 从 bus.links 过滤可见对端 (双向 Link + enabled)."""
    bus = _make_bus()
    bus.add_link(InterAgentLink(from_agent="a1", to_agent="a2", direction="both"))
    bus.add_link(InterAgentLink(from_agent="a1", to_agent="a3", direction="both"))
    bus.add_link(InterAgentLink(from_agent="a1", to_agent="a4", enabled=False))  # disabled
    broker = MeshActionBroker(bus)
    peers = broker.list_available("a1")
    assert set(peers) == {"a2", "a3"}


def test_list_available_no_bus_returns_empty() -> None:
    broker = MeshActionBroker()
    assert broker.list_available("a1") == []


# ── 默认 deny-by-default 零行为变化 ─────────────────────────────


@pytest.mark.asyncio
async def test_broker_without_bus_rejects_all_actions() -> None:
    """无 bus 注入时所有动作拒绝 (不抛, 不投递)."""
    broker = MeshActionBroker()
    policy = _policy(["notify", "handoff", "memory_query"])
    assert await broker.notify("a1", "a2", "x", policy) is False
    assert await broker.handoff("a1", "a2", "x", policy) is False
    assert await broker.memory_query("a1", "a2", "x", policy) is False


# ── 辅助 ────────────────────────────────────────────────────────


def _make_deliver_capture(sent: list[InterAgentMessage]) -> Callable[[str, InterAgentMessage], Awaitable[str | None]]:
    """构造 bus.deliver 回调: 把投递的消息塞进 sent 列表, 返回 None."""

    async def _deliver(_agent_id: str, msg: InterAgentMessage) -> str | None:
        sent.append(msg)
        return None

    return _deliver


# 避免 asyncio 未使用警告
_ = asyncio
