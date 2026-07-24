"""J1 用量记录器 (SPECIFICATION.md 2.3)。

在 Provider 调用边界被调用: ``record`` 是同步非阻塞的热路径入口, 只做成本估算与
入队缓冲; ``flush`` 由生命周期 stop / 周期任务调用, 把缓冲事件落库。写入失败只记
日志、绝不阻塞或中断主模型调用。

骨架状态: 缓冲 + 定价 + flush/aggregate 接口就位; 周期性异步 flush、背压与采样
留待 J1 实现节点。
"""

from __future__ import annotations

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


class UsageRecorder:
    """模型用量记录器: 估算成本 → 缓冲 → 落库。"""

    def __init__(
        self,
        store: UsageStore | None = None,
        pricing: PricingCatalog | None = None,
        *,
        buffer_maxlen: int = 10_000,
    ) -> None:
        self._store = store
        self._pricing = pricing
        self._buffer: deque[ModelUsageEvent] = deque(maxlen=buffer_maxlen)

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
        fallback_from: str | None = None,
    ) -> None:
        """从一次 LLM chat 调用构造并缓冲用量事件 (供 ProviderManager 调用)。

        失败请求 (response=None) 用量保持 0 并记录 status。trace_id/request_id 等
        完整上下文的贯穿由 J1 实现节点补齐。
        """
        usage = response.usage if response is not None else TokenUsage()
        event = ModelUsageEvent(
            event_id=uuid.uuid4().hex,
            trace_id="",
            request_id="",
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

    async def flush(self) -> None:
        """把缓冲事件落库。单条失败不影响其余; store 缺失时清空缓冲。"""
        if self._store is None:
            self._buffer.clear()
            return
        pending = list(self._buffer)
        self._buffer.clear()
        for event in pending:
            try:
                await self._store.insert(event)
            except Exception as exc:
                logger.warning("用量事件落库失败, 跳过该条", event_id=event.event_id, error=str(exc))

    async def aggregate(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """按维度聚合用量 (委托 UsageStore)。store 缺失时返回空列表。"""
        if self._store is None:
            return []
        return await self._store.aggregate(filters)
