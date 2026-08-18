"""U7 模型能力快照: models.dev 数据 → 本地 JSON → 能力/可达性过滤。

管线 (DEVELOPMENT_PLAN §四 U7, 拍板 #4 数据源 = models.dev):
1. ``scripts/gen_model_capabilities.py`` 拉取 models.dev api.json 归一化为
   ``data/model_capabilities.json`` (CI 每周刷新 + 手动补录 overrides 合并);
2. 本模块加载快照供路由层使用 —— ModelDescriptor 注册时合并快照能力
   (supports_tools/vision/context window), ModelRouter 按能力与可达性过滤;
3. 新鲜度: ``fresh(max_age_days)`` 供 CI drift 报警 (快照过期 → 测试失败)。

快照缺失/过期不阻塞运行 (能力未知按保守默认处理), 只影响路由精细度。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 快照 schema 版本 (归一化格式变更时 +1)
SNAPSHOT_SCHEMA_VERSION = 1


@dataclass
class ModelCapability:
    """单个模型的能力快照条目。"""

    provider_id: str
    model_id: str
    context_window: int | None = None
    supports_tools: bool | None = None  # None = 未知 (保守不判定)
    supports_vision: bool | None = None
    modalities_in: set[str] = field(default_factory=set)
    modalities_out: set[str] = field(default_factory=set)
    cost_tier: str = ""  # 快照侧可选标注; 空 = 未标注 (路由按 unknown)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CapabilitySnapshot:
    """模型能力快照 (generated_at + 按 provider/model 索引的能力表)。"""

    generated_at: str = ""
    source: str = ""
    schema_version: int = SNAPSHOT_SCHEMA_VERSION
    models: dict[str, ModelCapability] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> CapabilitySnapshot:
        """加载快照文件; 缺失/损坏返回空快照 (路由回落保守默认, 不阻塞)。"""
        file_path = Path(path)
        if not file_path.is_file():
            logger.debug("模型能力快照不存在", path=str(file_path))
            return cls()
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("模型能力快照损坏, 按空快照处理", path=str(file_path), error=str(exc))
            return cls()
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CapabilitySnapshot:
        models: dict[str, ModelCapability] = {}
        for key, entry in (raw.get("models") or {}).items():
            if not isinstance(entry, dict) or "/" not in key:
                continue
            provider_id, _, model_id = key.partition("/")
            models[key.lower()] = ModelCapability(
                provider_id=provider_id,
                model_id=model_id,
                context_window=entry.get("context_window"),
                supports_tools=entry.get("supports_tools"),
                supports_vision=entry.get("supports_vision"),
                modalities_in=set(entry.get("modalities_in") or ()),
                modalities_out=set(entry.get("modalities_out") or ()),
                cost_tier=str(entry.get("cost_tier") or ""),
                extra={k: v for k, v in entry.items() if k.startswith("x_")},
            )
        return cls(
            generated_at=str(raw.get("generated_at") or ""),
            source=str(raw.get("source") or ""),
            schema_version=int(raw.get("schema_version", SNAPSHOT_SCHEMA_VERSION)),
            models=models,
        )

    def get(self, provider_id: str, model_id: str) -> ModelCapability | None:
        """按 (provider_id, model_id) 查询能力 (大小写不敏感); 未收录返回 None。"""
        return self.models.get(f"{provider_id}/{model_id}".lower())

    def fresh(self, max_age_days: int = 60, *, now: datetime | None = None) -> bool:
        """新鲜度检查: generated_at 距今 <= max_age_days 天。

        无 generated_at (空快照) 视为不新鲜 —— CI drift 报警语义: 快照必须定期产出。
        """
        if not self.generated_at:
            return False
        try:
            stamp = datetime.fromisoformat(self.generated_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        now = now or datetime.now(UTC)
        return (now - stamp).days <= max_age_days

    def __len__(self) -> int:
        return len(self.models)
