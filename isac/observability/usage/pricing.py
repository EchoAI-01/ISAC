"""J1 价格目录与成本快照 (SPECIFICATION.md 2.3)。

成本用"调用时价格快照"计算, 不写死在 Provider 代码里; 价格未知时保存用量但
``estimated_cost=None``; 历史记录不因后续调价重算。

骨架状态: 内存价目表 + lookup / estimate_cost 接口就位; 真实价目加载 (配置/远程)、
多档计价 (input/output/cache/audio/非 Token 单位) 留待 J1 实现节点。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from isac.observability.usage.models import ModelUsageEvent


@dataclass
class PriceSnapshot:
    """某模型在某价格版本下的单价快照 (Decimal 字符串, 避免浮点误差)。"""

    provider: str
    model: str
    modality: str
    pricing_version: str
    input_price_per_unit: str = "0"
    output_price_per_unit: str = "0"
    unit_name: str = "token"
    currency: str = "USD"


class PricingCatalog:
    """价格目录: 按 (provider, model, modality) 查快照并估算成本。"""

    def __init__(self, snapshots: list[PriceSnapshot] | None = None, version: str = "") -> None:
        self.version = version
        self._by_key: dict[tuple[str, str, str], PriceSnapshot] = {}
        for snapshot in snapshots or []:
            self.register(snapshot)

    def register(self, snapshot: PriceSnapshot) -> None:
        """登记一条价格快照。"""
        self._by_key[(snapshot.provider, snapshot.model, snapshot.modality)] = snapshot

    def lookup(self, provider: str, model: str, modality: str) -> PriceSnapshot | None:
        """查询价格快照; 未登记返回 None。"""
        return self._by_key.get((provider, model, modality))

    def estimate_cost(self, event: ModelUsageEvent) -> str | None:
        """按调用时价格快照估算成本 (Decimal 字符串)。未知价格返回 None。

        骨架: 仅按 prompt/completion token 粗算。
        TODO(J1): 用 Decimal 分别计价 cache/reasoning/audio 与非 Token 单位, 并区分档位。
        """
        snapshot = self.lookup(event.provider, event.model, event.modality)
        if snapshot is None:
            return None
        total = Decimal(snapshot.input_price_per_unit) * Decimal(event.usage.prompt_tokens) + Decimal(
            snapshot.output_price_per_unit
        ) * Decimal(event.usage.completion_tokens)
        return str(total)
