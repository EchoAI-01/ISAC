"""L1 (2026-10-13 review): Channel 交互工具服务接线测试。

背景: channel_send / channel_history / channel_forward 三服务键此前全仓零生产
注入, send_emoji / send_image / fetch_history / view_forward_message 四个默认
allow 的工具在 LLM schema 可见但调用恒失败 (08-21 盘点遗留①)。本文件验证
isac/channel/services.py 的真实后端闭包 + OneBot fetch_forward 能力发现 +
switch_chat 默认降 deny 的口径。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from isac.channel.model import ISACMessage
from isac.channel.services import (
    build_channel_forward,
    build_channel_send,
    build_session_history_fetcher,
)


class _FakeAdapter:
    def __init__(self, platform: str, *, send_ok: bool = True) -> None:
        self.platform_name = platform
        self.sent: list[ISACMessage] = []
        self._send_ok = send_ok

    async def send(self, message: ISACMessage) -> bool:
        self.sent.append(message)
        return self._send_ok


class _FakeRegistry:
    def __init__(self, adapters: list[Any]) -> None:
        self._adapters = adapters

    def get(self, platform: str) -> Any | None:
        return next((a for a in self._adapters if a.platform_name == platform), None)

    def list(self) -> list[Any]:
        return list(self._adapters)


def _msg(platform: str = "qq", *, group_id: str | None = "g1") -> ISACMessage:
    return ISACMessage(
        msg_id="m1", platform=platform, timestamp=0, user_id="u1", user_name="用户",
        group_id=group_id, session_id="s1", content="hi",
    )


# ── channel_send ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_channel_send_routes_by_platform() -> None:
    qq = _FakeAdapter("qq")
    web = _FakeAdapter("webchat", send_ok=False)
    sender = build_channel_send(_FakeRegistry([qq, web]))
    assert sender is not None

    assert await sender(_msg("qq")) is True
    assert len(qq.sent) == 1
    # 平台路由正确: webchat 适配器不受影响。
    assert not web.sent
    # 适配器返回 False → 上报 False (工具向 LLM 报失败)。
    assert await sender(_msg("webchat")) is False


@pytest.mark.asyncio
async def test_channel_send_missing_adapter_and_none_registry() -> None:
    sender = build_channel_send(_FakeRegistry([]))
    assert await sender(_msg("telegram")) is False
    # registry 未注入 (无 Channel 场景) → 服务为 None (工具走友好错误分支)。
    assert build_channel_send(None) is None


# ── channel_history (U1 事件流) ─────────────────────────────


@pytest.mark.asyncio
async def test_channel_history_reads_recent_content_events(tmp_path: Path) -> None:
    from isac.session.event_store import SessionEventStore
    from isac.session.models import (
        EVENT_TOOL_CALLED,
        EVENT_TURN_COMPLETED,
        EVENT_USER_MESSAGE,
        SessionEvent,
    )

    store = SessionEventStore(str(tmp_path / "events.db"))
    await store.start()
    try:
        # 分区键 = agent:platform:group (与 manager 写侧 session_key_for 同源)。
        key = "agent_a:qq:group:g1"
        ts = 1_700_000_000
        for i in range(8):
            await store.append(SessionEvent(
                session_key=key, event_type=EVENT_USER_MESSAGE, timestamp=ts + i,
                payload={"content": f"问题{i}", "user_name": "用户"},
            ))
            await store.append(SessionEvent(
                session_key=key, event_type=EVENT_TURN_COMPLETED, timestamp=ts + i,
                payload={"content": f"回答{i}"},
            ))
            await store.append(SessionEvent(  # 工具事件不进历史
                session_key=key, event_type=EVENT_TOOL_CALLED, timestamp=ts + i,
                payload={"tool": "x"},
            ))
        await store.flush()

        fetcher = build_session_history_fetcher(store, "agent_a")
        assert fetcher is not None
        messages = await fetcher(_msg("qq"), limit=4)
        # 取**最近** 4 条内容事件 (问题7/回答7/问题6/回答6), 非窗口内最旧。
        assert [m.content for m in messages] == ["问题6", "回答6", "问题7", "回答7"]
        # user 事件带说话人, assistant 事件 (turn.completed) 不带。
        assert messages[0].user_name == "用户"
        assert messages[1].user_name == ""

        # 其他会话分区不受串扰。
        other = await fetcher(_msg("qq", group_id="g2"), limit=10)
        assert other == []

        assert build_session_history_fetcher(None, "agent_a") is None
    finally:
        await store.stop()


# ── channel_forward (能力发现) ──────────────────────────────


class _ForwardAdapter(_FakeAdapter):
    def __init__(self, platform: str, nodes: list | None = None, *, fail: bool = False) -> None:
        super().__init__(platform)
        self._nodes = nodes or []
        self._fail = fail

    async def fetch_forward(self, forward_id: str) -> list:
        if self._fail:
            raise RuntimeError("boom")
        return list(self._nodes)


@pytest.mark.asyncio
async def test_channel_forward_capability_discovery() -> None:
    from isac.channel.services import ChannelHistoryMessage

    qq = _ForwardAdapter("qq", nodes=[ChannelHistoryMessage(user_name="甲", content="转发内容")])
    tg = _FakeAdapter("telegram")  # 无 fetch_forward 能力 → 跳过
    fetcher = build_channel_forward(_FakeRegistry([tg, qq]))
    assert fetcher is not None

    out = await fetcher("resid-1")
    assert len(out) == 1 and out[0].content == "转发内容"


@pytest.mark.asyncio
async def test_channel_forward_adapter_failure_and_no_capability() -> None:
    bad = _ForwardAdapter("qq", fail=True)
    fetcher = build_channel_forward(_FakeRegistry([bad, _FakeAdapter("webchat")]))
    # 能力适配器失败 → 尝试其余 → 无可用 → 空列表 (工具报"当前平台不支持/已失效")。
    assert await fetcher("resid-1") == []
    # 全 registry 无能力 → 空列表。
    no_cap = build_channel_forward(_FakeRegistry([_FakeAdapter("qq")]))
    assert no_cap is not None
    assert await no_cap("resid-1") == []
    assert build_channel_forward(None) is None


# ── OneBot fetch_forward (get_forward_msg) ──────────────────


def _make_onebot_with_bot(raw: Any) -> Any:
    from isac.channel.adapters.onebot.adapter import OneBotAdapter

    adapter = OneBotAdapter({"host": "127.0.0.1", "port": 8080})

    class _FakeBot:
        async def call_action(self, action: str, **kwargs: Any) -> Any:
            assert action == "get_forward_msg"
            return raw

    adapter._bot = _FakeBot()
    return adapter


@pytest.mark.asyncio
async def test_onebot_fetch_forward_list_form() -> None:
    adapter = _make_onebot_with_bot([
        {"sender": {"nickname": "甲", "user_id": "10001"},
         "content": [{"type": "text", "data": {"text": "第一层"}},
                     {"type": "image", "data": {"url": "http://x"}}]},
        {"sender": {"card": "乙", "user_id": "10002"},
         "content": [{"type": "at", "data": {"qq": "10001"}},
                     {"type": "text", "data": {"text": "第二层"}}]},
    ])
    out = await adapter.fetch_forward("resid-9")
    assert [m.user_name for m in out] == ["甲", "乙"]
    assert out[0].content == "第一层 [图片]"
    assert out[1].content == "@10001 第二层"


@pytest.mark.asyncio
async def test_onebot_fetch_forward_messages_dict_form_and_guards() -> None:
    """go-cqhttp 风格 {"messages": [...]} 载荷 + 空参/未连接守卫。"""
    adapter = _make_onebot_with_bot({"messages": [
        {"sender": {"nickname": "丙"}, "content": "纯文本节点"},
    ]})
    out = await adapter.fetch_forward("resid-8")
    assert len(out) == 1 and out[0].content == "纯文本节点"

    # 空 id → 空列表; 未连接 (bot=None) → 抛错 (上层能力发现按失败处理)。
    assert await adapter.fetch_forward("") == []
    adapter._bot = None
    with pytest.raises(RuntimeError):
        await adapter.fetch_forward("resid-8")


# ── switch_chat 默认 deny (Q0 口径) ─────────────────────────


def test_switch_chat_default_deny_hidden_from_schema() -> None:
    """话题机制无存储/消费方 → 默认 deny, 不出现在 LLM schema (修复前默认
    allow 且恒失败, LLM 反复调用死工具)。显式配置仍可开启 (check 覆盖语义)。"""
    from isac.agent.tools.base import ToolPermission
    from isac.agent.tools.registry import ToolRegistry
    from isac.agent.tools.social.switch_chat import SwitchChatTool

    assert ToolPermission().check("switch_chat") == "deny"
    registry = ToolRegistry(ToolPermission())
    registry.register(SwitchChatTool())
    names = {d["name"] for d in registry.definitions()}
    assert "switch_chat" not in names
    # 显式开启后恢复可见 (策略表可覆盖默认)。
    enabled = ToolRegistry(ToolPermission({"switch_chat": "allow"}))
    enabled.register(SwitchChatTool())
    assert "switch_chat" in {d["name"] for d in enabled.definitions()}
