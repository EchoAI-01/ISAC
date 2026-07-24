"""/agents /focus /mute /unmute 4 个内置命令接入真实状态机的回归测试
(CODE_REVIEW_REPORT.md #10)。

此前 4 个 execute 均抛 NotImplementedError; 现在分别接入:
- /agents    -> AgentManager.list()
- /focus     -> GatingSystem.focus_mode.enter/exit
- /mute      -> Session.muted_until 写入
- /unmute    -> Session.muted_until 清除
"""

from __future__ import annotations

import time

import pytest

from isac.channel.model import ISACMessage
from isac.commands.builtin.agents import AgentsCommand
from isac.commands.builtin.focus import FocusCommand
from isac.commands.builtin.mute import MuteCommand, UnmuteCommand
from isac.commands.registry import CommandRegistry
from isac.core.types import AgentContext
from isac.gateway.models import Session
from isac.gating.system import GatingSystem


def _make_session(agent_id: str = "default") -> Session:
    return Session(
        session_id="sess-1",
        user_id="u1",
        agent_id=agent_id,
        platform="webchat",
        group_id=None,
        is_group=False,
        created_at=int(time.time()),
    )


def _make_message(content: str) -> ISACMessage:
    return ISACMessage(
        msg_id="m1",
        platform="webchat",
        timestamp=int(time.time()),
        user_id="u1",
        user_name="U1",
        group_id=None,
        content=content,
    )


class _FakeInstance:
    """最小 AgentInstance 替身, 只暴露 list() 需要的字段。"""

    def __init__(self, agent_id: str, display_name: str, status: str) -> None:
        self.agent_id = agent_id
        self.config = type("C", (), {"display_name": display_name})()
        self.status = status


class _FakeAgentManager:
    """最小 AgentManager 替身, 只暴露 list()。"""

    def __init__(self, instances: list) -> None:
        self._instances = instances

    async def list(self) -> list:
        return list(self._instances)


def _make_context(session: Session, services: dict | None = None) -> AgentContext:
    return AgentContext(
        session=session,
        user_profile=None,
        current_message=_make_message(""),
        services=services or {},
    )


@pytest.mark.asyncio
async def test_agents_command_lists_running_and_stopped() -> None:
    cmd = AgentsCommand()
    running_inst = _FakeInstance("a1", "A1", "running")
    stopped_inst = _FakeInstance("a2", "A2", "stopped")
    manager = _FakeAgentManager([running_inst, stopped_inst])
    ctx = _make_context(_make_session(), services={"agent_manager": manager})

    result = await cmd.execute(_make_message("/agents"), "", ctx)

    assert "当前 Agent 列表" in result
    assert "a1" in result and "A1" in result
    assert "running" in result
    assert "a2" in result and "stopped" in result


@pytest.mark.asyncio
async def test_agents_command_without_manager_returns_message() -> None:
    cmd = AgentsCommand()
    ctx = _make_context(_make_session(), services={})
    result = await cmd.execute(_make_message("/agents"), "", ctx)
    assert "未注入" in result


@pytest.mark.asyncio
async def test_focus_command_enters_focus_mode() -> None:
    cmd = FocusCommand()
    gating = GatingSystem()
    session = _make_session()
    ctx = _make_context(session, services={"gating": gating})

    result = await cmd.execute(_make_message("/focus"), "", ctx)

    assert "已开启专注模式" in result
    assert gating.focus_mode.is_active(session.session_id)


@pytest.mark.asyncio
async def test_focus_command_off_exits_focus_mode() -> None:
    cmd = FocusCommand()
    gating = GatingSystem()
    session = _make_session()
    gating.focus_mode.enter(session.session_id, duration=300)
    ctx = _make_context(session, services={"gating": gating})

    result = await cmd.execute(_make_message("/focus off"), "off", ctx)

    assert "已关闭" in result
    assert not gating.focus_mode.is_active(session.session_id)


@pytest.mark.asyncio
async def test_focus_command_custom_duration() -> None:
    cmd = FocusCommand()
    gating = GatingSystem()
    session = _make_session()
    ctx = _make_context(session, services={"gating": gating})

    result = await cmd.execute(_make_message("/focus 120"), "120", ctx)

    assert "120" in result
    assert gating.focus_mode.is_active(session.session_id)


@pytest.mark.asyncio
async def test_focus_command_invalid_arg() -> None:
    cmd = FocusCommand()
    gating = GatingSystem()
    session = _make_session()
    ctx = _make_context(session, services={"gating": gating})

    result = await cmd.execute(_make_message("/focus abc"), "abc", ctx)

    assert "无效参数" in result
    assert not gating.focus_mode.is_active(session.session_id)


@pytest.mark.asyncio
async def test_mute_command_sets_muted_until() -> None:
    cmd = MuteCommand()
    session = _make_session()
    ctx = _make_context(session)

    before = time.monotonic()
    result = await cmd.execute(_make_message("/mute 600"), "600", ctx)

    assert "已静音" in result and "600" in result
    assert session.muted_until > before


@pytest.mark.asyncio
async def test_mute_command_default_duration() -> None:
    cmd = MuteCommand()
    session = _make_session()
    ctx = _make_context(session)

    await cmd.execute(_make_message("/mute"), "", ctx)

    # 默认 1 小时, muted_until 应当在未来较远的时间
    assert session.muted_until > time.monotonic() + 3000


@pytest.mark.asyncio
async def test_unmute_command_clears_muted_until() -> None:
    cmd = UnmuteCommand()
    session = _make_session()
    session.muted_until = time.monotonic() + 3600
    ctx = _make_context(session)

    result = await cmd.execute(_make_message("/unmute"), "", ctx)

    assert "已取消静音" in result
    assert session.muted_until == 0.0


@pytest.mark.asyncio
async def test_unmute_command_when_not_muted() -> None:
    cmd = UnmuteCommand()
    session = _make_session()
    ctx = _make_context(session)

    result = await cmd.execute(_make_message("/unmute"), "", ctx)
    assert "并未静音" in result


@pytest.mark.asyncio
async def test_registry_dispatches_builtin_commands() -> None:
    """CommandRegistry 应能完整调度 4 个内置命令, 不再有 NotImplementedError。"""
    registry = CommandRegistry()
    registry.register(AgentsCommand())
    registry.register(FocusCommand())
    registry.register(MuteCommand())
    registry.register(UnmuteCommand())

    gating = GatingSystem()
    session = _make_session()
    ctx = _make_context(
        session,
        services={"gating": gating, "agent_manager": _FakeAgentManager([])},
    )

    # /agents
    r1 = await registry.try_execute(_make_message("/agents"), ctx)
    assert r1 is not None and "当前没有 Agent" in r1

    # /focus 60
    r2 = await registry.try_execute(_make_message("/focus 60"), ctx)
    assert r2 is not None and "60" in r2
    assert gating.focus_mode.is_active(session.session_id)

    # /mute
    r3 = await registry.try_execute(_make_message("/mute 120"), ctx)
    assert r3 is not None and "120" in r3
    assert session.muted_until > 0

    # /unmute
    r4 = await registry.try_execute(_make_message("/unmute"), ctx)
    assert r4 is not None and "已取消静音" in r4
    assert session.muted_until == 0.0
