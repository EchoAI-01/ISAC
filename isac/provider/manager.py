"""ProviderManager: Provider 池化管理 + 重试 + 回退 (SPECIFICATION.md 5.1/5.2)。

Provider 共享池，可按 Agent 配置 (AgentConfig.llm) 创建独立实例。
错误处理: 重试 3 次 (指数退避) → 回退到 fallback_model → 降级回复。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any

from isac.core.exceptions import LLMError, RateLimitError
from isac.core.types import LLMResponse
from isac.provider.base import LLMProvider
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.observability.metrics import MetricsCollector
    from isac.observability.usage.recorder import UsageRecorder
    from isac.runtime.config import AgentConfig

logger = get_logger(__name__)

DEGRADED_REPLY = "我现在有点累，稍后再聊好吗？"  # 降级回复 (LLM 全部失败时)


class ProviderManager:
    """Provider 管理器。"""

    def __init__(
        self,
        config: dict[str, Any],
        metrics: MetricsCollector | None = None,
        usage_recorder: UsageRecorder | None = None,
    ):
        self.config = config
        self._primary: LLMProvider | None = None
        self._fallback: LLMProvider | None = None
        self._agent_providers: dict[str, LLMProvider] = {}
        self._metrics = metrics
        # J1: 模型用量记录器 (默认 None → 不计量, 主链路热路径零变化)。
        self._usage_recorder = usage_recorder
        # J2: 多模态 Provider 池 (按 (provider_id, model_id) 索引)
        # 媒体工具通过 multimodal_provider(provider_id, model_id) 取实例。
        self._multimodal_providers: dict[tuple[str, str], Any] = {}

    def register(self, provider: LLMProvider, *, fallback: bool = False) -> None:
        """注册全局 Provider (main.py 组装时调用)。"""
        if fallback:
            self._fallback = provider
        else:
            self._primary = provider

    def register_multimodal(
        self,
        provider: Any,
        *,
        provider_id: str,
        model_id: str,
    ) -> None:
        """J2: 注册多模态 Provider (image_gen/stt/tts/embed/vision 等)。

        按 (provider_id, model_id) 索引, 与 ModelDescriptor 字段对齐。
        媒体工具通过 model_router.select 拿到 descriptor 后, 调
        multimodal_provider(descriptor.provider_id, descriptor.model_id) 取实例。
        """
        self._multimodal_providers[(provider_id, model_id)] = provider

    def multimodal_provider(self, provider_id: str, model_id: str) -> Any | None:
        """J2: 按 (provider_id, model_id) 查询多模态 Provider; 未注册返回 None。"""
        return self._multimodal_providers.get((provider_id, model_id))

    async def invalidate_agent_provider(self, agent_id: str) -> None:
        """Q0: 失效某 Agent 的独立 Provider 缓存 (reload_config/destroy 时调用)。

        此前 ``_agent_providers`` 按 agent_id 缓存后全仓无失效点, PATCH 修改
        AgentConfig.llm 后 ``for_agent`` 仍返回旧 Provider, 换模型必须重启进程。
        对被移除的 Provider 尽力 aclose 释放连接池 (无 aclose 或失败时静默跳过)。
        """
        provider = self._agent_providers.pop(agent_id, None)
        if provider is None:
            return
        close = getattr(provider, "aclose", None)
        if close is not None:
            try:
                await close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Agent Provider 关闭失败, 缓存已失效", agent_id=agent_id, error=str(exc))
        logger.info("Agent Provider 缓存已失效", agent_id=agent_id)

    async def aclose(self) -> None:
        """关闭所有已注册 Provider 的底层连接池 (ApplicationRuntime 关闭时调用)。

        对没有 aclose() 的 Provider (如 StubProvider) 静默跳过。
        """
        seen: set[int] = set()
        all_providers = [
            self._primary,
            self._fallback,
            *self._agent_providers.values(),
            *self._multimodal_providers.values(),
        ]
        for provider in all_providers:
            if provider is None or id(provider) in seen:
                continue
            seen.add(id(provider))
            close = getattr(provider, "aclose", None)
            if close is None:
                continue
            try:
                await close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Provider 关闭失败, 继续关闭其他", error=str(exc))

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

    async def chat_with_retry(
        self,
        provider: LLMProvider,
        *,
        agent_id: str = "",
        session_id: str = "",
        trace_id: str = "",
        **kwargs: Any,
    ) -> LLMResponse:
        """LLM 调用: 重试 3 次 (指数退避) → 回退模型 → 降级回复 (SPECIFICATION.md 5.2)。

        agent_id/session_id/trace_id 是关联 ID (J1), 不进入转发给 provider.chat()
        的 kwargs; trace_id 由调用方为这一次逻辑调用统一生成/传入 (含其所有重试与
        回退尝试), 用于聚合时按 trace_id 归并同一逻辑调用产生的多条 ModelUsageEvent。

        TODO: 区分错误类型 (RateLimitError 退避更久)。
        """
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return await self._call_and_record(
                    provider, agent_id=agent_id, session_id=session_id, trace_id=trace_id, **kwargs
                )
            except RateLimitError as exc:
                last_error = exc
                logger.warning("LLM 限流，退避重试", attempt=attempt + 1)
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
            except LLMError as exc:
                last_error = exc
                logger.warning("LLM 调用失败", attempt=attempt + 1, error=str(exc))
                if not exc.retriable:
                    break
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
            except Exception as exc:  # noqa: BLE001
                # Provider 具体实现可能抛出非 LLMError 异常 (网络库异常/JSON 解析失败等)。
                # 规范化为可重试错误继续走既有 重试/回退/降级 流程, 而不是让异常直接
                # 冒泡打断整条消息处理链路 (调用方 main.py 没有兜底 try/except)。
                last_error = exc
                logger.warning("LLM 调用出现非预期异常，按可重试处理", attempt=attempt + 1, error=str(exc))
                if attempt < 2:
                    await asyncio.sleep(2**attempt)

        if self._fallback is not None:
            logger.warning("回退到备选模型", model=self._fallback.get_model_name())
            try:
                return await self._call_and_record(
                    self._fallback,
                    agent_id=agent_id,
                    session_id=session_id,
                    trace_id=trace_id,
                    fallback_from=provider.get_model_name(),
                    **kwargs,
                )
            except Exception as exc:
                last_error = exc

        logger.error("LLM 全部失败，降级回复", error=str(last_error))
        return LLMResponse(content=DEGRADED_REPLY)

    async def _call_and_record(
        self,
        provider: LLMProvider,
        *,
        agent_id: str = "",
        session_id: str = "",
        trace_id: str = "",
        fallback_from: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """调用 provider.chat() 并记录 isac_llm_* 指标与 J1 用量事件。

        成功和失败都记录一次物理请求 (SPECIFICATION.md 2.3): 失败时用量保持 0
        并标记 status=failed。指标与用量记录都在 finally 中完成, 记录失败不影响主调用。
        request_id 是这一次物理尝试的唯一 ID, 每次调用都重新生成 (与 trace_id 不同,
        trace_id 由调用方在重试/回退的多次尝试之间共享)。
        """
        start = time.monotonic()
        status = "success"
        response: LLMResponse | None = None
        request_id = uuid.uuid4().hex
        if self._metrics is not None:
            self._metrics.counter("isac_llm_calls_total").inc()
        try:
            response = await provider.chat(**kwargs)
            return response
        except Exception:
            status = "failed"
            if self._metrics is not None:
                self._metrics.counter("isac_llm_errors_total").inc()
            raise
        finally:
            elapsed = time.monotonic() - start
            if self._metrics is not None:
                self._metrics.histogram("isac_llm_latency_seconds").observe(elapsed)
                if response is not None:
                    self._metrics.counter("isac_llm_tokens_total").inc(response.usage.total_tokens)
            self._record_usage(
                provider,
                response,
                status,
                int(elapsed * 1000),
                agent_id=agent_id,
                session_id=session_id,
                trace_id=trace_id,
                request_id=request_id,
                fallback_from=fallback_from,
            )

    def record_stream_result(
        self,
        provider: LLMProvider,
        response: LLMResponse | None,
        *,
        latency_ms: int,
        status: str = "success",
        agent_id: str = "",
        session_id: str = "",
        trace_id: str = "",
    ) -> None:
        """流式调用记录 isac_llm_* 指标与 J1 用量事件 (ISACAgentLoop._call_llm 流式分支调用)。

        流式响应不经过 chat_with_retry (中途已把 chunk 推给 on_chunk 回调, 无法在
        中断后干净重试), 因此不含重试/回退逻辑, 只补记录这一次物理请求本身;
        response 为 None 表示流式过程中失败, 用量保持 0 并记录 status=failed。
        """
        if self._metrics is not None:
            self._metrics.counter("isac_llm_calls_total").inc()
            self._metrics.histogram("isac_llm_latency_seconds").observe(latency_ms / 1000)
            if response is not None:
                self._metrics.counter("isac_llm_tokens_total").inc(response.usage.total_tokens)
            if status != "success":
                self._metrics.counter("isac_llm_errors_total").inc()
        self._record_usage(
            provider,
            response,
            status,
            latency_ms,
            agent_id=agent_id,
            session_id=session_id,
            trace_id=trace_id,
            request_id=uuid.uuid4().hex,
        )

    def _record_usage(
        self,
        provider: LLMProvider,
        response: LLMResponse | None,
        status: str,
        latency_ms: int,
        *,
        agent_id: str = "",
        session_id: str = "",
        trace_id: str = "",
        request_id: str = "",
        fallback_from: str | None = None,
    ) -> None:
        """J1: 缓冲一次模型用量事件。recorder 为 None 时惰性跳过, 失败不影响主调用。"""
        recorder = self._usage_recorder
        if recorder is None:
            return
        try:
            recorder.record_llm(
                model=provider.get_model_name(),
                provider=type(provider).__name__,
                response=response,
                status=status,
                latency_ms=latency_ms,
                agent_id=agent_id,
                session_id=session_id,
                trace_id=trace_id,
                request_id=request_id,
                fallback_from=fallback_from,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("模型用量记录失败, 已忽略", error=str(exc))
