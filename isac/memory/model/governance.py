"""记忆治理骨架 (N2, MEMORY_DESIGN.md §7)。

[框架已搭建 / scaffolding] freeze/protect/correct/delete/restore/export 六类治理动作的
挂接点就位;真正的权限校验、审计、纠错可追溯历史留待 N2 实现节点 (见 TODO)。
默认全部为 no-op (返回 False = 未执行), 不触碰既有 metadata.py 存储。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.memory.storage.metadata import MetadataStore

logger = get_logger(__name__)


class MemoryGovernor:
    """记忆治理器骨架 (freeze/protect/correct/delete/restore/export)。

    组合 MetadataStore, 但骨架阶段不执行任何写操作 (no-op), 供 N2 实现节点填充。
    """

    def __init__(self, metadata_store: MetadataStore | None = None) -> None:
        self._store = metadata_store

    async def freeze(self, item_id: str) -> bool:
        """冻结记忆条目 (不再自动更新)。TODO(N2): 置 frozen=True + 审计。"""
        logger.debug("记忆治理 freeze (骨架 no-op)", item_id=item_id)
        return False

    async def protect(self, item_id: str) -> bool:
        """保护记忆条目 (不被自动清理/覆盖)。TODO(N2): 置 protected=True + 审计。"""
        return False

    async def correct(self, item_id: str, new_content: str) -> bool:
        """纠正记忆内容 (保留可追溯历史)。TODO(N2): 写新版本 + 关系 corrected_by。"""
        _ = new_content
        return False

    async def delete(self, item_id: str) -> bool:
        """删除记忆条目。TODO(N2): 软删除 + 审计, protected 条目拒绝。"""
        return False

    async def restore(self, item_id: str) -> bool:
        """恢复被删除/冻结的条目。TODO(N2): 反向操作 + 审计。"""
        return False

    async def export(self, agent_id: str) -> list[Any]:
        """导出某 Agent 的记忆 (合规/迁移)。TODO(N2): 组织为 MemoryItem 列表。"""
        _ = agent_id
        return []
