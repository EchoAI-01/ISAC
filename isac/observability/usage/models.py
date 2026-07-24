"""J1 计量数据契约 (SPECIFICATION.md 2.3)。"""

from __future__ import annotations

from dataclasses import dataclass, field

from isac.core.types import TokenUsage


@dataclass
class ModelUsageEvent:
    """一次模型请求的标准计量事件。

    每次物理 API 请求 (含重试、回退、多模态生成) 必须独立记录, 不能只记录最终成功
    响应; 失败请求用量未知时保持 0 并记录 status, 禁止估算 Token 冒充实际值。
    成本由 ``PricingCatalog`` 用调用时价格快照计算, 未知价格时 ``estimated_cost=None``。
    """

    event_id: str
    trace_id: str
    request_id: str
    agent_id: str
    session_id: str
    provider: str
    model: str
    modality: str  # text | embedding | rerank | stt | tts | image | video
    operation: str  # chat | embed | rerank | transcribe | synthesize | generate
    usage: TokenUsage = field(default_factory=TokenUsage)
    input_units: float = 0.0  # 图片张数、音频秒数、视频秒数等非 Token 单位
    output_units: float = 0.0
    unit_name: str = "token"
    estimated_cost: str | None = None  # Decimal 字符串; 无价格快照时为 None
    currency: str = "USD"
    pricing_version: str = ""
    latency_ms: int = 0
    status: str = "success"  # success | failed | cancelled
    fallback_from: str | None = None
    created_at: int = 0
