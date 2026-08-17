"""U2 用量栈构造器: UsageStore + UsageRecorder。

原 isac/main.py 的 _build_usage_stack 归位 observability 层 (U2 装配层重构)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)

DATA_DIR = Path("data")

def _build_usage_stack(global_config: dict[str, Any]) -> tuple[Any, Any]:
    """J1: 模型用量计量子系统 (默认关闭; observability.usage.enabled=true 时启用)。

    未启用时返回 (None, None) → ProviderManager 不计量, 主链路热路径零变化,
    也不会创建任何 usage.db 文件。
    """
    usage_config = (global_config.get("observability", {}) or {}).get("usage", {}) or {}
    if not usage_config.get("enabled"):
        return None, None
    from isac.observability.usage.pricing import PricingCatalog
    from isac.observability.usage.recorder import UsageRecorder
    from isac.observability.usage.storage import UsageStore

    usage_store = UsageStore(str(DATA_DIR / "usage" / "usage.db"))
    # R1-④: 加载价目表 (provider/model/modality → 价格快照); 文件不存在用空 catalog,
    # estimated_cost 恒 None (向后兼容)。与 ③ record_* 传的 provider/model 对齐闭环。
    pricing = PricingCatalog.load(DATA_DIR / "pricing.jsonc")
    usage_recorder = UsageRecorder(
        store=usage_store,
        pricing=pricing,
        flush_interval_seconds=float(usage_config.get("flush_interval_seconds", 30)),
    )
    return usage_store, usage_recorder
