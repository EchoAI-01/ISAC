"""Q0 开箱可触达与配置纠偏 (DEVELOPMENT_PLAN.md §四 Q0)。

覆盖:
- main._register_channel_adapters: 四平台按配置注册 / 未启用零注册
- main._ensure_default_routing: 裸部署兜底默认路由 / 已配置规则不动
- web_search 默认策略 deny
- task 工具 restricted 门接受 subagent_supervisor 或 task_runner 任一后端
- ProviderManager.invalidate_agent_provider: 缓存失效 + aclose + 重建
- MetadataStore.delete_namespace: 按命名空间硬删三表且不影响其他命名空间
- SparseBM25Index.clear: 清空内存索引
"""

from __future__ import annotations

from pathlib import Path

import pytest

from isac.channel.registry import ChannelRegistry
from isac.core.types import ToolCall
from isac.main import _ensure_default_routing, _register_channel_adapters
from isac.memory.storage.metadata import MetadataStore
from isac.memory.storage.sparse import SparseBM25Index
from isac.provider.manager import ProviderManager
from isac.router.router import MessageRouter
from isac.router.types import RoutingRules

# ── Channel 注册分支 ──────────────────────────────────────────


def test_register_channel_adapters_all_four_platforms() -> None:
    """四平台 enabled=true 时全部注册 (构造不触发任何网络/绑定 I/O)。"""
    registry = ChannelRegistry()
    _register_channel_adapters(
        registry,
        {
            "channels": {
                "onebot": {"enabled": True, "host": "127.0.0.1", "port": 18080},
                "telegram": {"enabled": True, "bot_token": "t"},
                "discord": {"enabled": True, "bot_token": "d"},
                "webchat": {"enabled": True, "bind_host": "127.0.0.1", "bind_port": 18090},
            }
        },
    )
    platforms = {adapter.platform_name for adapter in registry.list()}
    assert platforms == {"qq", "telegram", "discord", "webchat"}


def test_register_channel_adapters_disabled_registers_nothing() -> None:
    registry = ChannelRegistry()
    _register_channel_adapters(
        registry,
        {"channels": {"onebot": {"enabled": False}, "webchat": {"enabled": False}}},
    )
    assert registry.list() == []


def test_register_channel_adapters_missing_channels_section() -> None:
    registry = ChannelRegistry()
    _register_channel_adapters(registry, {})
    assert registry.list() == []


# ── 裸部署默认路由 ────────────────────────────────────────────


def _registry_with_webchat() -> ChannelRegistry:
    registry = ChannelRegistry()
    _register_channel_adapters(
        registry, {"channels": {"webchat": {"enabled": True, "bind_port": 18091}}}
    )
    return registry


def _make_router(rules: RoutingRules) -> MessageRouter:
    return MessageRouter(rules, agents_provider=lambda: [])


def test_ensure_default_routing_fills_empty_rules() -> None:
    """规则完全为空时, 每个已注册平台登记默认 Agent。"""
    router = _make_router(RoutingRules())
    _ensure_default_routing(router, _registry_with_webchat(), "default")
    assert router.get_rules().default_agents == {"webchat": "default"}


def test_ensure_default_routing_keeps_existing_rules() -> None:
    """用户显式配置过任何路由 (哪怕别的平台) 时完全不动, 保留有意的 DROP 语义。"""
    rules = RoutingRules(default_agents={"qq": "my-agent"})
    router = _make_router(rules)
    _ensure_default_routing(router, _registry_with_webchat(), "default")
    assert router.get_rules().default_agents == {"qq": "my-agent"}


def test_ensure_default_routing_no_platforms_noop() -> None:
    router = _make_router(RoutingRules())
    _ensure_default_routing(router, ChannelRegistry(), "default")
    assert router.get_rules().default_agents == {}


# ── task restricted 门: 备选服务键 ────────────────────────────


def _make_agent_context():
    from isac.core.types import AgentContext, Budget
    from isac.gateway.models import Session

    return AgentContext(
        session=Session(session_id="s1", agent_id="a1", user_id="u1", platform="test"),
        user_profile=None,
        current_message=None,
        budget=Budget(max_iterations=3),
    )


@pytest.mark.asyncio
async def test_task_gate_rejects_without_any_backend() -> None:
    from isac.agent.tools.base import ToolPermission
    from isac.agent.tools.registry import ToolRegistry
    from isac.agent.tools.utility.task import TaskTool

    registry = ToolRegistry(ToolPermission())
    registry.register(TaskTool())
    result = await registry.execute(
        ToolCall(id="c1", name="task", arguments={"task": "x"}), _make_agent_context(), services={}
    )
    assert result.is_error is True
    assert "subagent_supervisor" in result.content


@pytest.mark.asyncio
async def test_task_gate_accepts_task_runner_fallback() -> None:
    """旧 task_runner 路径仍可通过 restricted 门 (向后兼容)。"""
    from isac.agent.tools.base import ToolPermission
    from isac.agent.tools.registry import ToolRegistry
    from isac.agent.tools.utility.task import TaskTool
    from isac.core.types import ToolResult

    async def runner(task: str, *, budget: int, parent_context, depth: int = 0, max_depth: int = 3) -> ToolResult:
        return ToolResult(content=f"done: {task}")

    registry = ToolRegistry(ToolPermission())
    registry.register(TaskTool())
    result = await registry.execute(
        ToolCall(id="c1", name="task", arguments={"task": "分析"}),
        _make_agent_context(),
        services={"task_runner": runner, "task_depth": 0, "task_max_depth": 3},
    )
    assert result.is_error is False
    assert "done: 分析" in result.content


# ── ProviderManager 缓存失效 ──────────────────────────────────


class _ClosableStub:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_invalidate_agent_provider_evicts_and_closes() -> None:
    from isac.runtime.config import AgentConfig

    pm = ProviderManager({})
    config = AgentConfig(
        agent_id="a1", llm={"provider": "stub", "api_key": "k", "model": "m"}
    )
    first = pm.for_agent(config)
    assert pm.for_agent(config) is first  # 命中缓存
    # 换成带 aclose 的假 Provider 验证关闭被调用
    stub = _ClosableStub()
    pm._agent_providers["a1"] = stub  # noqa: SLF001
    await pm.invalidate_agent_provider("a1")
    assert stub.closed is True
    assert "a1" not in pm._agent_providers  # noqa: SLF001
    # 失效后重建: 拿到新实例而非旧缓存
    rebuilt = pm.for_agent(config)
    assert rebuilt is not stub


@pytest.mark.asyncio
async def test_invalidate_agent_provider_missing_is_noop() -> None:
    pm = ProviderManager({})
    await pm.invalidate_agent_provider("nonexistent")  # 不抛异常


# ── MetadataStore.delete_namespace ───────────────────────────


@pytest.mark.asyncio
async def test_delete_namespace_removes_only_target_agent(tmp_path: Path) -> None:
    store = MetadataStore(str(tmp_path / "meta.db"))
    await store.init_schema()
    await store.store_episode("agent-a", {"content": "apple_pie_recipe", "session_id": "s1", "user_id": "u1"})
    await store.store_episode("agent-a", {"content": "orange_jam_recipe", "session_id": "s1", "user_id": "u1"})
    await store.store_episode("agent-b", {"content": "apple_pie_recipe", "session_id": "s2", "user_id": "u2"})
    await store.upsert_person_profile("agent-a", {"person_id": "p1", "name": "小明"})
    await store.upsert_jargon("agent-a", "yyds", "永远的神")

    removed = await store.delete_namespace("agent-a")

    assert removed == 2
    assert await store.search_fts("agent-a", "apple_pie_recipe") == []
    assert await store.get_person_profile("agent-a", "p1") is None
    assert await store.list_jargon("agent-a") == []
    # 其他命名空间不受影响
    remaining = await store.search_fts("agent-b", "apple_pie_recipe")
    assert len(remaining) == 1


@pytest.mark.asyncio
async def test_send_reply_routes_by_platform_session_key() -> None:
    """Q0: 出站回复按平台会话键路由 (gateway 把 session_id 改写为内部 sess_* 之前的键)。

    此前 WebChat 回复落在内部 sess_* 键下, 客户端按自己的 session_id 轮询永远
    拿不到回复 (真实启动冒烟发现的开箱不可聊根因之一)。
    """
    from isac.channel.adapters.webchat.adapter import WebChatAdapter
    from isac.channel.model import ISACMessage
    from isac.main import _send_reply

    adapter = WebChatAdapter({"bind_port": 18192})
    registry = ChannelRegistry()
    registry.register(adapter)
    # 模拟 gateway 改写后的入站消息: session_id 已是内部 sess_*, 平台键单独传递
    incoming = ISACMessage(
        msg_id="m1", platform="webchat", timestamp=0, user_id="tester",
        user_name="tester", group_id=None, session_id="sess_internal", content="hi",
    )
    await _send_reply(registry, incoming, "回复内容", "default", platform_session_id="client-key")

    assert await adapter.poll_replies("client-key") != []  # 客户端按自己的键取到回复
    assert await adapter.poll_replies("sess_internal") == []  # 不落内部键


def test_sparse_index_clear_resets_all_state() -> None:
    index = SparseBM25Index()
    index.add("m1", "hello world")
    index.add("m2", "hello again")
    assert index.search("hello") != []
    index.clear()
    assert index.search("hello") == []
    index.add("m3", "hello fresh")  # clear 后可继续正常使用
    assert [mid for mid, _ in index.search("hello")] == ["m3"]
