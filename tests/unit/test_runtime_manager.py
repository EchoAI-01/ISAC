"""AgentManager.handle_message() 会话级状态隔离测试 (CODE_REVIEW_REPORT.md #6)。

修复前 GatingSystem 只持有单例 TurnScheduler/IdleBackoffController, 被同一 Agent
服务的所有会话共享；本测试交错调用两个不同 session 的 handle_message(), 验证
它们各自的话轮频率状态互不污染。
"""

from __future__ import annotations

import pytest

from isac.channel.model import ISACMessage, MessageSegment
from isac.gateway.models import Session
from isac.memory.pipeline import NoOpMemoryPipeline
from isac.provider.llm.stub import StubProvider
from isac.provider.manager import ProviderManager
from isac.runtime.config import AgentConfig
from isac.runtime.manager import AgentManager

AGENT_ID = "agent_a"


async def _make_running_agent_manager() -> AgentManager:
    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
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


def _at_message(msg_id: str, user_id: str) -> ISACMessage:
    """带 @ 分段的消息, 强制门控直接 TRIGGER, 不依赖 reply_necessity 评分的不确定性。"""
    return ISACMessage(
        msg_id=msg_id,
        platform="webchat",
        timestamp=0,
        user_id=user_id,
        user_name=user_id,
        content="你好",
        segments=[MessageSegment(type="at", data={})],
    )


@pytest.mark.asyncio
async def test_interleaved_sessions_have_independent_turn_scheduler_state() -> None:
    manager = await _make_running_agent_manager()
    session_a = Session(session_id="sess_a", user_id="u_a", agent_id=AGENT_ID)
    session_b = Session(session_id="sess_b", user_id="u_b", agent_id=AGENT_ID)

    # session_a 与 session_b 交错调用, session_a 交互轮次远多于 session_b。
    for i in range(10):
        await manager.handle_message(AGENT_ID, _at_message(f"a{i}", "u_a"), session_a, None)
        if i == 0:
            await manager.handle_message(AGENT_ID, _at_message("b0", "u_b"), session_b, None)

    instance = await manager.get(AGENT_ID)
    assert instance is not None
    scheduler_a = instance.gating.get_turn_scheduler(session_a.session_id)
    scheduler_b = instance.gating.get_turn_scheduler(session_b.session_id)

    assert scheduler_a is not scheduler_b
    # session_a: 10 轮, 每轮 1 条用户消息 + 1 条 Bot 回复 (StubProvider 总是非空回复);
    # recent_window_messages 统计窗口内全部事件 (含 Bot 自己的回复), 故为 2 * 轮数。
    assert scheduler_a.recent_window_messages == 20
    assert scheduler_a.recent_self_replies == 10
    # session_b 只交互了 1 轮, 不应被 session_a 后续 9 轮历史污染。
    assert scheduler_b.recent_window_messages == 2
    assert scheduler_b.recent_self_replies == 1


@pytest.mark.asyncio
async def test_interleaved_sessions_have_independent_idle_backoff_instances() -> None:
    manager = await _make_running_agent_manager()
    session_a = Session(session_id="sess_a", user_id="u_a", agent_id=AGENT_ID)
    session_b = Session(session_id="sess_b", user_id="u_b", agent_id=AGENT_ID)

    await manager.handle_message(AGENT_ID, _at_message("a0", "u_a"), session_a, None)
    await manager.handle_message(AGENT_ID, _at_message("b0", "u_b"), session_b, None)

    instance = await manager.get(AGENT_ID)
    assert instance is not None
    backoff_a = instance.gating.get_idle_backoff(session_a.session_id)
    backoff_b = instance.gating.get_idle_backoff(session_b.session_id)

    assert backoff_a is not backoff_b


@pytest.mark.asyncio
async def test_agent_lifecycle_records_metrics() -> None:
    """create/start/stop/destroy 应记录对应指标并维护 isac_agents_active 门数

    (CODE_REVIEW_REPORT.md #5)。
    """
    from isac.observability import get_default_metrics

    metrics = get_default_metrics()
    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    manager = AgentManager(
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
            "metrics": metrics,
        }
    )

    await manager.create(AgentConfig(agent_id="agent_x"))
    assert metrics.counter("isac_agent_creates_total").value() == 1

    await manager.start("agent_x")
    assert metrics.counter("isac_agent_starts_total").value() == 1
    assert metrics.gauge("isac_agents_active").value() == 1

    await manager.stop("agent_x")
    assert metrics.counter("isac_agent_stops_total").value() == 1
    assert metrics.gauge("isac_agents_active").value() == 0

    await manager.start("agent_x")
    assert metrics.gauge("isac_agents_active").value() == 1
    await manager.destroy("agent_x")
    assert metrics.gauge("isac_agents_active").value() == 0


@pytest.mark.asyncio
async def test_load_persisted_agents_restores_enabled_agents(tmp_path) -> None:
    """重启恢复: data/agents/<id>/config.jsonc 的 enabled=true Agent 自动 create+start
    (CODE_REVIEW_REPORT.md #2)。"""
    from isac.runtime.config import save_agent_config
    from isac.runtime.manager import load_persisted_agents

    agents_dir = tmp_path / "agents"
    # 写两个 Agent: a 启用, b 禁用
    save_agent_config(agents_dir / "a" / "config.jsonc", AgentConfig(agent_id="a", display_name="A"))
    save_agent_config(
        agents_dir / "b" / "config.jsonc",
        AgentConfig(agent_id="b", display_name="B", enabled=False),
    )

    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    manager = AgentManager(
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        }
    )

    report = await load_persisted_agents(manager, str(agents_dir))

    assert report["a"] == "running"
    assert report["b"] == "stopped"
    inst_a = await manager.get("a")
    inst_b = await manager.get("b")
    assert inst_a is not None and inst_a.status == "running"
    assert inst_b is not None and inst_b.status == "stopped"


@pytest.mark.asyncio
async def test_load_persisted_agents_skips_invalid_config(tmp_path) -> None:
    """损坏的 config.jsonc 不阻塞其他 Agent 恢复 (CODE_REVIEW_REPORT.md #2)。"""
    from isac.runtime.manager import load_persisted_agents

    agents_dir = tmp_path / "agents"
    (agents_dir / "broken" / "config.jsonc").parent.mkdir(parents=True, exist_ok=True)
    (agents_dir / "broken" / "config.jsonc").write_text("{not valid json", encoding="utf-8")

    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    manager = AgentManager(
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        }
    )

    report = await load_persisted_agents(manager, str(agents_dir))

    assert report["broken"].startswith("failed:")
    # 没有任何 Agent 被加载到内存
    assert await manager.list_ids() == []


@pytest.mark.asyncio
async def test_load_persisted_agents_missing_dir_returns_empty(tmp_path) -> None:
    """目录不存在时返回空报告, 不抛异常。"""
    from isac.runtime.manager import load_persisted_agents

    provider_manager = ProviderManager({})
    provider_manager.register(StubProvider())
    manager = AgentManager(
        {
            "provider_manager": provider_manager,
            "memory_factory": lambda namespace: NoOpMemoryPipeline(namespace),
            "global_config": {},
        }
    )

    report = await load_persisted_agents(manager, str(tmp_path / "nonexistent"))
    assert report == {}
