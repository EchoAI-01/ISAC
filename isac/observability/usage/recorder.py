"""J1 用量记录器 (SPECIFICATION.md 2.3)。

在 Provider 调用边界被调用: ``record`` 是同步非阻塞的热路径入口, 只做成本估算与
入队缓冲; ``flush`` 把缓冲事件批量落库, 由 ``start()``/``stop()`` 生命周期驱动的
周期任务自动调用, 也可在测试/关闭时手动调用。写入失败只记日志、绝不阻塞或中断
主模型调用。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections import deque
from typing import TYPE_CHECKING, Any

from isac.core.types import TokenUsage
from isac.observability.usage.models import ModelUsageEvent
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.core.types import LLMResponse
    from isac.observability.usage.pricing import PricingCatalog
    from isac.observability.usage.storage import UsageStore

logger = get_logger(__name__)

DEFAULT_FLUSH_INTERVAL_SECONDS = 30.0


class UsageRecorder:
    """模型用量记录器: 估算成本 → 缓冲 → 周期性批量落库。"""

    def __init__(
        self,
        store: UsageStore | None = None,
        pricing: PricingCatalog | None = None,
        *,
        buffer_maxlen: int = 10_000,
        flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        self._store = store
        self._pricing = pricing
        self._buffer: deque[ModelUsageEvent] = deque(maxlen=buffer_maxlen)
        self._flush_interval_seconds = max(0.001, flush_interval_seconds)
        self._running = False
        self._task: asyncio.Task[None] | None = None

    @property
    def pending_count(self) -> int:
        """当前缓冲区未落库事件数 (供监控 / 测试)。"""
        return len(self._buffer)

    def record(self, event: ModelUsageEvent) -> None:
        """缓冲一条用量事件 (同步非阻塞)。

        未知价格时保持 ``estimated_cost=None`` (不伪造成本); 任何异常都不冒泡。
        """
        try:
            if event.estimated_cost is None and self._pricing is not None:
                cost = self._pricing.estimate_cost(event)
                if cost is not None:
                    event.estimated_cost = cost
                    event.pricing_version = self._pricing.version
            self._buffer.append(event)
        except Exception as exc:
            logger.warning("用量事件缓冲失败, 已忽略", error=str(exc))

    def record_llm(
        self,
        *,
        model: str,
        provider: str = "",
        response: LLMResponse | None = None,
        status: str = "success",
        latency_ms: int = 0,
        agent_id: str = "",
        session_id: str = "",
        trace_id: str = "",
        request_id: str = "",
        fallback_from: str | None = None,
    ) -> None:
        """从一次 LLM chat 调用构造并缓冲用量事件 (供 ProviderManager 调用)。

        失败请求 (response=None) 用量保持 0 并记录 status。trace_id 由调用方为一次
        逻辑调用 (含其所有重试/回退尝试) 统一生成; request_id 由调用方为每次物理
        尝试单独生成, 二者用于聚合时按 trace_id 归并同一逻辑调用的多次物理请求。
        """
        usage = response.usage if response is not None else TokenUsage()
        event = ModelUsageEvent(
            event_id=uuid.uuid4().hex,
            trace_id=trace_id,
            request_id=request_id,
            agent_id=agent_id,
            session_id=session_id,
            provider=provider,
            model=model or (response.model if response is not None else ""),
            modality="text",
            operation="chat",
            usage=usage,
            latency_ms=latency_ms,
            status=status,
            fallback_from=fallback_from,
            created_at=int(time.time()),
        )
        self.record(event)

    # ── J2 多模态计量: 非 token 单位 (image/audio/video/embed/rerank) ─────
    # 每个方法仿 record_llm 结构: 构造 ModelUsageEvent → self.record() (估算成本 + 缓冲)
    # input_units/output_units 按 modality 语义填:
    #   image_gen: input_units=n_images (生成请求次数), output_units=n_images (生成图片数)
    #   stt:       input_units=duration_seconds (输入音频时长)
    #   tts:       output_units=duration_seconds (输出音频时长)
    #   video:     understand→input_units=duration; generate→output_units=duration
    #   embed:     input_units=n_texts, output_units=dim (向量维度, 不直接计价)
    #   rerank:    input_units=n_candidates
    # 失败请求 (status != "success") 用量保持 0 不伪造, 但仍记录事件。

    def record_image_gen(
        self,
        *,
        model: str,
        provider: str = "",
        n_images: int = 1,
        latency_ms: int = 0,
        status: str = "success",
        agent_id: str = "",
        session_id: str = "",
        trace_id: str = "",
        request_id: str = "",
        fallback_from: str | None = None,
    ) -> None:
        """图片生成调用计量: modality=image, operation=generate, unit=image。"""
        event = ModelUsageEvent(
            event_id=uuid.uuid4().hex,
            trace_id=trace_id,
            request_id=request_id,
            agent_id=agent_id,
            session_id=session_id,
            provider=provider,
            model=model,
            modality="image",
            operation="generate",
            input_units=n_images,
            output_units=n_images,
            unit_name="image",
            latency_ms=latency_ms,
            status=status,
            fallback_from=fallback_from,
            created_at=int(time.time()),
        )
        self.record(event)

    def record_stt(
        self,
        *,
        model: str,
        provider: str = "",
        duration_seconds: float = 0.0,
        latency_ms: int = 0,
        status: str = "success",
        agent_id: str = "",
        session_id: str = "",
        trace_id: str = "",
        request_id: str = "",
        fallback_from: str | None = None,
    ) -> None:
        """语音转写调用计量: modality=audio, operation=transcribe, unit=second。"""
        event = ModelUsageEvent(
            event_id=uuid.uuid4().hex,
            trace_id=trace_id,
            request_id=request_id,
            agent_id=agent_id,
            session_id=session_id,
            provider=provider,
            model=model,
            modality="audio",
            operation="transcribe",
            input_units=duration_seconds,
            unit_name="second",
            latency_ms=latency_ms,
            status=status,
            fallback_from=fallback_from,
            created_at=int(time.time()),
        )
        self.record(event)

    def record_tts(
        self,
        *,
        model: str,
        provider: str = "",
        duration_seconds: float = 0.0,
        latency_ms: int = 0,
        status: str = "success",
        agent_id: str = "",
        session_id: str = "",
        trace_id: str = "",
        request_id: str = "",
        fallback_from: str | None = None,
    ) -> None:
        """语音合成调用计量: modality=audio, operation=synthesize, unit=second。"""
        event = ModelUsageEvent(
            event_id=uuid.uuid4().hex,
            trace_id=trace_id,
            request_id=request_id,
            agent_id=agent_id,
            session_id=session_id,
            provider=provider,
            model=model,
            modality="audio",
            operation="synthesize",
            output_units=duration_seconds,
            unit_name="second",
            latency_ms=latency_ms,
            status=status,
            fallback_from=fallback_from,
            created_at=int(time.time()),
        )
        self.record(event)

    def record_video(
        self,
        *,
        operation: str,
        model: str,
        provider: str = "",
        duration_seconds: float = 0.0,
        latency_ms: int = 0,
        status: str = "success",
        agent_id: str = "",
        session_id: str = "",
        trace_id: str = "",
        request_id: str = "",
        fallback_from: str | None = None,
    ) -> None:
        """视频调用计量: modality=video, unit=second。
        operation 由调用方传 (understand/generate); understand→input_units=duration,
        generate→output_units=duration。
        """
        event = ModelUsageEvent(
            event_id=uuid.uuid4().hex,
            trace_id=trace_id,
            request_id=request_id,
            agent_id=agent_id,
            session_id=session_id,
            provider=provider,
            model=model,
            modality="video",
            operation=operation,
            input_units=duration_seconds if operation == "understand" else 0.0,
            output_units=duration_seconds if operation == "generate" else 0.0,
            unit_name="second",
            latency_ms=latency_ms,
            status=status,
            fallback_from=fallback_from,
            created_at=int(time.time()),
        )
        self.record(event)

    def record_embed(
        self,
        *,
        model: str,
        provider: str = "",
        n_texts: int = 1,
        dim: int = 0,
        latency_ms: int = 0,
        status: str = "success",
        agent_id: str = "",
        session_id: str = "",
        trace_id: str = "",
        request_id: str = "",
        fallback_from: str | None = None,
    ) -> None:
        """Embedding 调用计量: modality=embedding, operation=embed, unit=vector。
        input_units=n_texts (向量化文本数), output_units=dim (向量维度, 不直接计价,
        真实 OpenAI 按 token 计价; 此处用 vector 单位做简化模型)。
        """
        event = ModelUsageEvent(
            event_id=uuid.uuid4().hex,
            trace_id=trace_id,
            request_id=request_id,
            agent_id=agent_id,
            session_id=session_id,
            provider=provider,
            model=model,
            modality="embedding",
            operation="embed",
            input_units=n_texts,
            output_units=dim,
            unit_name="vector",
            latency_ms=latency_ms,
            status=status,
            fallback_from=fallback_from,
            created_at=int(time.time()),
        )
        self.record(event)

    def record_rerank(
        self,
        *,
        model: str,
        provider: str = "",
        n_candidates: int = 0,
        latency_ms: int = 0,
        status: str = "success",
        agent_id: str = "",
        session_id: str = "",
        trace_id: str = "",
        request_id: str = "",
        fallback_from: str | None = None,
    ) -> None:
        """Reranker 调用计量: modality=rerank, operation=rerank, unit=candidate。"""
        event = ModelUsageEvent(
            event_id=uuid.uuid4().hex,
            trace_id=trace_id,
            request_id=request_id,
            agent_id=agent_id,
            session_id=session_id,
            provider=provider,
            model=model,
            modality="rerank",
            operation="rerank",
            input_units=n_candidates,
            unit_name="candidate",
            latency_ms=latency_ms,
            status=status,
            fallback_from=fallback_from,
            created_at=int(time.time()),
        )
        self.record(event)

    async def flush(self) -> None:
        """把缓冲事件一次性批量落库 (insert_many, 避免逐事件提交的 N+1 开销)。

        store 缺失时清空缓冲; 整批失败只记一条日志丢弃, 不做逐行重试 (缓冲事件
        来自内部构造, 格式错误概率极低, 批量整体失败优于极慢的逐条提交)。
        """
        if self._store is None:
            self._buffer.clear()
            return
        pending = list(self._buffer)
        self._buffer.clear()
        if not pending:
            return
        try:
            await self._store.insert_many(pending)
        except Exception as exc:
            logger.warning("用量事件批量落库失败, 整批丢弃", count=len(pending), error=str(exc))

    async def aggregate(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """按维度聚合用量 (委托 UsageStore)。store 缺失时返回空列表。"""
        if self._store is None:
            return []
        return await self._store.aggregate(filters)

    async def start(self) -> None:
        """启动周期性 flush (ApplicationRuntime 生命周期 start); 重复调用是 no-op。"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._flush_loop())
        logger.info("用量周期性 flush 已启动", interval=self._flush_interval_seconds)

    async def stop(self) -> None:
        """停止周期性 flush 并兜底再 flush 一次剩余缓冲 (生命周期 stop, LIFO)。"""
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        await self.flush()

    async def _flush_loop(self) -> None:
        """仿 AlertManager._check_loop: 循环 flush, 单次异常不终止循环。"""
        while self._running:
            try:
                await self.flush()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("周期性 flush 循环异常", error=str(exc))
            await asyncio.sleep(self._flush_interval_seconds)
