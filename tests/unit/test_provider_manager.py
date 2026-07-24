"""ProviderManager.chat_with_retry() 测试 (CODE_REVIEW_REPORT.md #11)。

Provider 具体实现可能抛出非 LLMError 异常 (网络库异常/JSON 解析错误等)；
chat_with_retry() 应把它们规范化为可重试错误, 继续走 重试/回退/降级 流程,
而不是让异常直接冒泡打断整条消息处理链路 (调用方没有兜底 try/except)。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from isac.core.types import LLMResponse, TokenUsage
from isac.provider.manager import DEGRADED_REPLY, ProviderManager


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """跳过重试指数退避的真实等待, 只验证重试次数/流程, 不为此耗费真实时间。"""

    async def _instant_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)


class _AlwaysRaisesProvider:
    """模拟抛出非 LLMError 异常的 Provider 实现 (比如网络库/JSON 解析失败)。"""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0

    async def chat(self, **kwargs):
        self.calls += 1
        raise self._exc

    async def chat_stream(self, *args, **kwargs):
        raise NotImplementedError

    def get_model_name(self) -> str:
        return "always-raises"

    def get_capabilities(self):
        return None


class _StubReplyProvider:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def chat(self, **kwargs) -> LLMResponse:
        return LLMResponse(content=self.reply, usage=TokenUsage(total_tokens=1))

    async def chat_stream(self, *args, **kwargs):
        raise NotImplementedError

    def get_model_name(self) -> str:
        return "stub"

    def get_capabilities(self):
        return None


@pytest.mark.asyncio
async def test_non_llm_error_triggers_fallback_instead_of_propagating() -> None:
    manager = ProviderManager({})
    primary = _AlwaysRaisesProvider(ValueError("boom"))
    fallback = _StubReplyProvider("fallback-ok")
    manager.register(fallback, fallback=True)

    result = await manager.chat_with_retry(primary, system="s", messages=[])

    assert result.content == "fallback-ok"
    assert primary.calls == 3  # 重试 3 次后才回退到 fallback


@pytest.mark.asyncio
async def test_non_llm_error_without_fallback_degrades_gracefully() -> None:
    manager = ProviderManager({})
    primary = _AlwaysRaisesProvider(json.JSONDecodeError("bad json", "{", 0))

    result = await manager.chat_with_retry(primary, system="s", messages=[])

    assert result.content == DEGRADED_REPLY
    assert primary.calls == 3


class _FakeAgentConfig:
    """最小 AgentConfig 替身, 仅提供 for_agent() 需要的字段。"""

    def __init__(self, agent_id: str, llm: dict | None) -> None:
        self.agent_id = agent_id
        self.llm = llm


def test_for_agent_returns_independent_provider_per_agent() -> None:
    """AgentConfig.llm 配置时为每个 agent 创建独立 Provider 并缓存 (CODE_REVIEW_REPORT.md #9)。"""
    manager = ProviderManager({})
    config_a = _FakeAgentConfig("a", {"provider": "openai", "api_key": "key-a", "model": "m-a"})
    config_b = _FakeAgentConfig("b", {"provider": "openai", "api_key": "key-b", "model": "m-b"})

    provider_a1 = manager.for_agent(config_a)
    provider_a2 = manager.for_agent(config_a)
    provider_b = manager.for_agent(config_b)

    assert provider_a1 is provider_a2  # 同 agent 缓存
    assert provider_a1 is not provider_b  # 不同 agent 独立
    assert provider_a1.get_model_name() == "m-a"
    assert provider_b.get_model_name() == "m-b"


def test_for_agent_falls_back_to_primary_when_llm_missing() -> None:
    """AgentConfig.llm 缺失或字段不完整时退回共享池 primary (CODE_REVIEW_REPORT.md #9)。"""
    manager = ProviderManager({})
    primary = _StubReplyProvider("primary")
    manager.register(primary)

    no_llm = _FakeAgentConfig("a", None)
    assert manager.for_agent(no_llm) is primary

    incomplete_llm = _FakeAgentConfig("b", {"provider": "openai"})  # 缺 api_key
    assert manager.for_agent(incomplete_llm) is primary


def test_for_agent_stub_provider() -> None:
    """provider=stub 时 Agent 独立 Provider 是 StubProvider (dev 兜底)。"""
    from isac.provider.llm.stub import StubProvider

    manager = ProviderManager({})
    config = _FakeAgentConfig("a", {"provider": "stub", "api_key": "dev"})
    provider = manager.for_agent(config)
    assert isinstance(provider, StubProvider)
