"""MemoryItem ↔ MemoryHit 适配器 (N1)。

让检索路径 (VectorStore/BM25Search → MemoryHit) 与统一 MemoryItem 互转,
供 MemoryRetrievalPipeline / injector 围绕 MemoryItem 读写。读路径只取已知
字段, 未知字段进 metadata 兜底。
"""

from __future__ import annotations

from typing import Any

from isac.core.types import MemoryHit
from isac.memory.model.memory_item import MemoryItem, MemoryScope, MemoryType


class MemoryItemAdapter:
    """MemoryItem ↔ MemoryHit 双向适配。"""

    @staticmethod
    def to_hit(item: MemoryItem, *, score: float = 0.0) -> MemoryHit:
        """把 MemoryItem 转成 MemoryHit (供检索结果统一消费)。

        source 取 metadata.session_id (episodes) 或 agent_id (jargon) 兜底;
        hit_type 取 memory_type.value; importance/scope 进 metadata。
        """
        source = str(item.metadata.get("session_id", "") or item.agent_id)
        hit_type = item.memory_type.value
        meta = dict(item.metadata)
        meta["importance"] = item.importance
        meta["agent_id"] = item.agent_id
        meta["scope"] = item.scope.value
        return MemoryHit(
            id=item.id,
            content=item.content,
            source=source,
            hit_type=hit_type,
            score=score,
            metadata=meta,
        )

    @staticmethod
    def from_hit(hit: MemoryHit) -> MemoryItem:
        """把 MemoryHit 转成 MemoryItem (供 injector 统一消费)。

        hit_type → memory_type (未知类型默认 EPISODE);
        source = session_id → subject_id (兜底 agent_id); metadata 透传。
        """
        memory_type = _HIT_TYPE_TO_MEMORY_TYPE.get(hit.hit_type, MemoryType.EPISODE)
        agent_id = str(hit.metadata.get("agent_id", "") or "")
        scope_value = str(hit.metadata.get("scope", "agent_private"))
        try:
            scope = MemoryScope(scope_value)
        except ValueError:
            scope = MemoryScope.AGENT_PRIVATE
        importance = float(hit.metadata.get("importance", 0.0) or 0.0)
        return MemoryItem(
            id=hit.id,
            agent_id=agent_id,
            scope=scope,
            subject_id=hit.source,  # source 通常是 session_id
            content=hit.content,
            memory_type=memory_type,
            importance=importance,
            metadata=_clean_metadata(hit.metadata),
        )


def _clean_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """去掉已映射到 MemoryItem 字段的 key, 避免重复。"""
    cleaned = {k: v for k, v in meta.items() if k not in {"agent_id", "scope", "importance"}}
    return cleaned


# 复用 memory_item 的映射表 (避免循环 import, 这里再声明一份引用)
from isac.memory.model.memory_item import _HIT_TYPE_TO_MEMORY_TYPE  # noqa: E402
