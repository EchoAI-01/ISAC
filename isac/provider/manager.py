"""ProviderManager: Provider 池化管理 + 重试 + 回退 (SPECIFICATION.md 5.1/5.2)。

Provider 共享池，可按 Agent 配置 (AgentConfig.llm) 创建独立实例。
错误处理: 重试 3 次 (指数退避) → 回退到 fallback_model → 降级回复。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from isac.core.exceptions import LLMError, RateLimitError
from isac.core.types import LLMResponse
from isac.provider.base import LLMProvider
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.observability.metrics import MetricsCollector
    from isac.runtime.config import AgentConfig

logger = get_logger(__name__)

DEGRADED_REPLY = "我现在有点累，稍后再聊好吗？"  # 降级回复 (LLM 全部失败时)


class ProviderManager:
    """Provider 管理器。"""

    def __init__(self, config: dict[str, Any], metrics: MetricsCollector | None = None):
        self.config = config
        self._primary: LLMProvider | None = None
        self._fallback: LLMProvider | None = None
        self._agent_providers: dict[str, LLMProvider] = {}
        self._metrics = metrics

    def register(self, provider: LLMProvider, *, fallback: bool = False) -> None:
        """注册全局 Provider (main.py 组装时调用)。"""
        if fallback:
            self._fallback = provider
        else:
            self._primary = provider

    def for_agent(self, config: AgentConfig) -> LLMProvider:
        """返回 Agent 可用的 Provider: 优先独立配置，否则共享池。

        Agent 级独立 Provider 由 AgentConfig.llm dict 描述 (provider/api_key/base_url/model);
        为每个 agent 缓存一个 LLMProvider 实例, 实现多 Agent 各自使用不同模型/凭据
        (CODE_REVIEW_REPORT.md #9)。
        """
        if config.llm:
            cached = self._agent_providers.get(config.agent_id)
            if cached is not None:
                return cached
            provider = self._build_agent_provider(config.llm)
            if provider is not None:
                self._agent_providers[config.agent_id] = provider
                return provider
            # config.llm 字段存在但缺少必要字段, 退回共享池 (并记录一次警告避免日志噪声)
            logger.warning(
                "Agent 配置了 llm 但字段不完整, 退回共享 Provider",
                agent_id=config.agent_id,
                llm_keys=sorted(config.llm.keys()),
            )
        if self._primary is None:
            raise LLMError("未注册任何 LLM Provider")
        return self._primary

    def _build_agent_provider(self, llm_config: dict[str, Any]) -> LLMProvider | None:
        """按 AgentConfig.llm 字典构造独立 Provider; 字段不完整返回 None。

        复用 OpenAICompatProvider 作为 OpenAI 兼容 API 适配器; 同时接受 StubProvider
        作为 dev 兜底 (provider=stub)。生产环境应由 register_llm_provider() 走相同的
        路径, 不在此处引入新的 Provider 类型。
        """
        provider_name = str(llm_config.get("provider") or "").strip().lower()
        api_key = str(llm_config.get("api_key") or "").strip()
        if not provider_name or not api_key:
            return None
        # 仅当 provider + api_key 同时存在才视为"已配置", 与 register_llm_provider() 的
        # 判定保持一致 (避免 agent 级与全局级出现分歧)。
        from isac.provider.llm.openai_compat import OpenAICompatProvider
        from isac.provider.llm.stub import StubProvider

        if provider_name == "stub":
            return StubProvider()
        return OpenAICompatProvider(
            api_key=api_key,
            base_url=str(llm_config.get("base_url") or ""),
            model=str(llm_config.get("model") or ""),
        )

    async def chat_with_retry(self, provider: LLMProvider, **kwargs: Any) -> LLMResponse:
        """LLM 调用: 重试 3 次 (指数退避) → 回退模型 → 降级回复 (SPECIFICATION.md 5.2)。

        TODO: 区分错误类型 (RateLimitError 退避更久)。
        """
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return await self._call_and_record(provider, **kwargs)
            except RateLimitError as exc:
                last_error = exc
                logger.warning("LLM 限流，退避重试", attempt=attempt + 1)
                await asyncio.sleep(2**attempt)
            except LLMError as exc:
                last_error = exc
                logger.warning("LLM 调用失败", attempt=attempt + 1, error=str(exc))
                if not exc.retriable:
                    break
                await asyncio.sleep(2**attempt)
            except Exception as exc:  # noqa: BLE001
                # Provider 具体实现可能抛出非 LLMError 异常 (网络库异常/JSON 解析失败等)。
                # 规范化为可重试错误继续走既有 重试/回退/降级 流程, 而不是让异常直接
                # 冒泡打断整条消息处理链路 (调用方 main.py 没有兜底 try/except)。
                last_error = exc
                logger.warning("LLM 调用出现非预期异常，按可重试处理", attempt=attempt + 1, error=str(exc))
                await asyncio.sleep(2**attempt)

        if self._fallback is not None:
            logger.warning("回退到备选模型", model=self._fallback.get_model_name())
            try:
                return await self._call_and_record(self._fallback, **kwargs)
            except Exception as exc:
                last_error = exc

        logger.error("LLM 全部失败，降级回复", error=str(last_error))
        return LLMResponse(content=DEGRADED_REPLY)

    async def _call_and_record(self, provider: LLMProvider, **kwargs: Any) -> LLMResponse:
        """调用 provider.chat() 并记录 isac_llm_* 指标 (调用数/失败数/延迟/token 用量)。"""
        if self._metrics is None:
            return await provider.chat(**kwargs)
        self._metrics.counter("isac_llm_calls_total").inc()
        start = time.monotonic()
        try:
            response = await provider.chat(**kwargs)
        except Exception:
            self._metrics.counter("isac_llm_errors_total").inc()
            raise
        finally:
            self._metrics.histogram("isac_llm_latency_seconds").observe(time.monotonic() - start)
        self._metrics.counter("isac_llm_tokens_total").inc(response.usage.total_tokens)
        return response
