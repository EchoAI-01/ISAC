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
    """notify ACL 通过时经 bus.send 真实投递 NOTIFY 消息, 返回 True。

    CR3-M2: 此前 bus 对 notify 在调用 _deliver 之前就 return None (消息被静默
    丢弃, 工具却报告成功)。修复后 notify 必须真实投递到目标 Agent (忽略响应)。
    """
    bus = _make_bus()
    bus.add_link(InterAgentLink(from_agent="a1", to_agent="a2", direction="both", enabled=True))
    sent: list[InterAgentMessage] = []
    bus.set_deliver(_make_deliver_capture(sent))
    broker = MeshActionBroker(bus)
    policy = _policy(["notify"])
    ok = await broker.notify("a1", "a2", "提醒用户喝水", policy)
    assert ok is True
    # CR3-M2: notify 必须真实调用 deliver 投递 (fire-and-forget: 忽略响应)
    assert len(sent) == 1
    assert sent[0].type == "notify"
    assert sent[0].to_agent == "a2"
    assert sent[0].content == "提醒用户喝水"


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
    # P2: memory_query 返回响应文本 (str) 而非 bool; deliver 返回 None → 空响应 ""
    response = await broker.memory_query("a1", "a2", "周末计划", policy)
    assert response is not None
    assert sent[0].type == MeshMessageType.MEMORY_QUERY.value
    # visible_memory_scopes 进 context.filters, 让接收方按 scope 裁剪
    assert sent[0].context.get("filters") == {"scopes": ["agent_private", "conversation"]}


@pytest.mark.asyncio
async def test_memory_query_returns_receiver_response() -> None:
    """P2: memory_query 同步取回接收方响应文本 (此前丢弃 response, 查询方拿不到结果)。"""
    bus = _make_bus()
    bus.add_link(InterAgentLink(from_agent="a1", to_agent="a2"))

    async def _deliver(_agent_id: str, _msg: InterAgentMessage) -> str:
        return "- 用户上周说想去爬山"

    bus.set_deliver(_deliver)
    broker = MeshActionBroker(bus)
    policy = _policy(["memory_query"])
    response = await broker.memory_query("a1", "a2", "周末计划", policy)
    assert response == "- 用户上周说想去爬山"


@pytest.mark.asyncio
async def test_memory_query_rejected_without_permission() -> None:
    """memory_query 不在 permissions 时拒绝, 不投递 (P2: 拒绝返回 None)."""
    bus = _make_bus()
    sent: list[InterAgentMessage] = []
    bus.set_deliver(_make_deliver_capture(sent))
    broker = MeshActionBroker(bus)
    policy = _policy(["notify"])  # 不含 memory_query
    response = await broker.memory_query("a1", "a2", "x", policy)
    assert response is None
    assert sent == []


def test_policy_for_resolves_from_link_fields() -> None:
    """P2: broker.policy_for 按 (from,to) 的 Link 字段解析策略; 无 Link 返回 None。"""
    bus = _make_bus()
    bus.add_link(
        InterAgentLink(
            from_agent="a1",
            to_agent="a2",
            permissions=["notify", "memory_query"],
            visible_memory_scopes=["user:u1"],
            max_context_messages=5,
        )
    )
    broker = MeshActionBroker(bus)
    policy = broker.policy_for("a1", "a2")
    assert policy is not None
    assert policy.permissions == ["notify", "memory_query"]
    assert policy.visible_memory_scopes == ["user:u1"]
    assert policy.max_context_messages == 5
    assert broker.policy_for("a1", "a9") is None  # 无 Link → None (deny-by-default)


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
    assert await broker.memory_query("a1", "a2", "x", policy) is None  # P2: 拒绝返回 None


# ── 辅助 ────────────────────────────────────────────────────────


def _make_deliver_capture(sent: list[InterAgentMessage]) -> Callable[[str, InterAgentMessage], Awaitable[str | None]]:
    """构造 bus.deliver 回调: 把投递的消息塞进 sent 列表, 返回 None."""

    async def _deliver(_agent_id: str, msg: InterAgentMessage) -> str | None:
        sent.append(msg)
        return None

    return _deliver


# 避免 asyncio 未使用警告
_ = asyncio
