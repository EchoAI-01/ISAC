"""J1 模型用量与成本计量子系统 (SPECIFICATION.md 2.3 / ARCHITECTURE.md)。

职责: 在 Provider 调用边界把每次物理模型请求记录为 ``ModelUsageEvent``,
按调用时价格快照估算成本, 持久化到 SQLite, 并支持多维聚合。

骨架状态: 数据契约 + 记录/定价/存储接口就位; 真实落库与聚合查询留待 J1 实现节点。
计量默认关闭 (config.observability.usage.enabled=false), 不注入时主链路热路径零变化。
"""

from __future__ import annotations

from isac.observability.usage.models import ModelUsageEvent
from isac.observability.usage.pricing import PriceSnapshot, PricingCatalog
from isac.observability.usage.recorder import UsageRecorder
from isac.observability.usage.storage import UsageStore

__all__ = [
    "ModelUsageEvent",
    "PriceSnapshot",
    "PricingCatalog",
    "UsageRecorder",
    "UsageStore",
]
