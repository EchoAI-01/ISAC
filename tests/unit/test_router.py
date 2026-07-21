"""MessageRouter 路由优先级单元测试 (ARCHITECTURE.md 3.2)。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from isac.router.router import MessageRouter
from isac.router.types import ChannelBinding, RoutingRules
from tests.fixtures.messages import make_isac_message


def run(coro):
    return asyncio.run(coro)


def make_router(agents=None, rules=None) -> MessageRouter:
    agents = agents or []
    rules = rules or RoutingRules()
    return MessageRouter(rules, agents_provider=lambda: agents)


class TestRoutingPriority:
    def test_binding_first(self):
        agents = [SimpleNamespace(agent_id="alice", trigger_words=["爱丽丝"])]
        rules = RoutingRules(
            bindings=[ChannelBinding(platform="qq", group_id="group_001", agent_id="bob")],
            default_agents={"qq": "alice"},
        )
        router = make_router(agents, rules)
        msg = make_isac_message(content="爱丽丝 你好")
        decision = run(router.route(msg))
        assert decision.agent_id == "bob"  # 绑定优先于触发词
        assert decision.matched_by == "binding"

    def test_trigger_word_stripped(self):
        agents = [SimpleNamespace(agent_id="alice", trigger_words=["爱丽丝"])]
        router = make_router(agents)
        msg = make_isac_message(content="爱丽丝 今天天气怎么样")
        decision = run(router.route(msg))
        assert decision.agent_id == "alice"
        assert decision.matched_by == "trigger_word"
        assert decision.content == "今天天气怎么样"  # 触发词已剥离

    def test_default_agent(self):
        agents = [SimpleNamespace(agent_id="alice", trigger_words=["爱丽丝"])]
        rules = RoutingRules(default_agents={"qq": "bob"})
        router = make_router(agents, rules)
        msg = make_isac_message(content="随便聊聊")
        decision = run(router.route(msg))
        assert decision.agent_id == "bob"
        assert decision.matched_by == "default"

    def test_no_match_drop(self):
        router = make_router()
        msg = make_isac_message(content="无人认领")
        assert run(router.route(msg)) is None

    def test_binding_platform_mismatch(self):
        rules = RoutingRules(
            bindings=[ChannelBinding(platform="telegram", agent_id="alice")],
        )
        router = make_router(rules=rules)
        msg = make_isac_message(platform="qq")
        assert run(router.route(msg)) is None

    def test_router_hook_before_binding(self):
        agents = []
        rules = RoutingRules(
            bindings=[ChannelBinding(platform="qq", agent_id="bob")],
        )
        router = make_router(agents, rules)

        async def hook(message):
            from isac.router.types import RoutingDecision

            return RoutingDecision(agent_id="hooked", matched_by="hook", content=message.content)

        router.register_router_hook(hook)
        msg = make_isac_message()
        decision = run(router.route(msg))
        assert decision.agent_id == "hooked"  # hook 优先级最高
