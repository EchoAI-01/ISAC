"""记忆治理 (N2, MEMORY_DESIGN.md §7)。

L5 实现: freeze/protect/correct/delete/restore/export 六类治理动作真实 SQL + 审计;
correct 保留可追溯历史 (memory_revisions 表); delete 软删除 + protected 拒绝;
restore 反向操作。不动既有 episodes 三表 schema (仅 _ensure_column 加治理列)。
治理是只读后端能力, 可默认开 (governance_enabled=True); 失败不阻塞主链路。
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

import aiosqlite

from isac.memory.model.memory_item import MemoryItem
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.memory.storage.metadata import MetadataStore

logger = get_logger(__name__)

# CR2-Fix-13: correct() 对 new_content 的最大字节长度; 超出截断, 防止治理接口
# 被当作"塞任意大小文本"的载体 (风格与 subagent/journal.py 的 max_log_bytes
# 截断惯例一致: 按字节截断 + errors="ignore" 丢弃残余多字节字符 + 追加后缀)。
_MAX_CORRECTED_CONTENT_BYTES = 20_000
_TRUNCATION_SUFFIX = "...(已截断)"


def _truncate_content(content: str, *, max_bytes: int = _MAX_CORRECTED_CONTENT_BYTES) -> str:
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content
    suffix_bytes = _TRUNCATION_SUFFIX.encode("utf-8")
    truncated = encoded[: max(0, max_bytes - len(suffix_bytes))].decode("utf-8", errors="ignore")
    return truncated + _TRUNCATION_SUFFIX


class MemoryGovernor:
    """记忆治理器 (freeze/protect/correct/delete/restore/export)。

    组合 MetadataStore; 通过 store.db_path 直连 SQLite 操作治理列与 memory_audit/
    memory_revisions 表。无 store 时所有操作安全返回 False / [] (不抛, 保持向后兼容)。
    """

    def __init__(self, metadata_store: MetadataStore | None = None) -> None:
        self._store = metadata_store

    def _db_path(self) -> str | None:
        if self._store is None:
            return None
        return self._store.db_path

    async def _item_exists(self, db_path: str, item_id: str, agent_id: str) -> bool:
        """检查 item 是否存在且属于指定 agent_id (幂等判定 + 跨 Agent 越权拦截)。

        CR2-Fix-11: 此前只按 item_id 判定存在性, 未校验 agent_id, 导致 URL 路径
        里的 {agent_id} 段形同摆设 —— 任何 agent_id 都能操作任意 item_id, 只要
        item 存在。加 agent_id 条件后, item 存在但属于别的 agent 时视为"不存在"
        (幂等语义: 返回 False, 不泄露"item 存在但属于别人"的信息)。
        """
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM episodes WHERE id = ? AND agent_id = ?", (item_id, agent_id)
            )
            return await cursor.fetchone() is not None

    async def _write_audit(self, db_path: str, item_id: str, action: str, *, detail: str = "") -> None:
        """写审计日志 (失败不阻塞主操作)。"""
        try:
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "INSERT INTO memory_audit (audit_id, item_id, action, operator, occurred_at, detail) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, item_id, action, "", int(time.time()), detail),
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("审计日志写入失败, 已忽略", action=action, item_id=item_id, error=str(exc))

    async def list_audit(self, item_id: str) -> list[dict[str, Any]]:
        """读取某条目的审计历史 (供导出/排查)。无 store 时返回空列表。"""
        db_path = self._db_path()
        if db_path is None:
            return []
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT audit_id, item_id, action, operator, occurred_at, detail "
                "FROM memory_audit WHERE item_id = ? ORDER BY occurred_at ASC",
                (item_id,),
            )
            rows = await cursor.fetchall()
        return [
            {
                "audit_id": r["audit_id"],
                "item_id": r["item_id"],
                "action": r["action"],
                "operator": r["operator"],
                "occurred_at": r["occurred_at"],
                "detail": r["detail"],
            }
            for r in rows
        ]

    async def freeze(self, item_id: str, agent_id: str) -> bool:
        """冻结记忆条目 (不再自动更新); 幂等。无 store 或不属于 agent_id 返回 False。"""
        db_path = self._db_path()
        if db_path is None or not await self._item_exists(db_path, item_id, agent_id):
            return False
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE episodes SET frozen = 1, updated_at = ? WHERE id = ? AND agent_id = ?",
                (int(time.time()), item_id, agent_id),
            )
            await db.commit()
        logger.info("记忆条目已冻结", item_id=item_id, agent_id=agent_id)
        await self._write_audit(db_path, item_id, "freeze")
        return True

    async def protect(self, item_id: str, agent_id: str) -> bool:
        """保护记忆条目 (不被自动清理/覆盖); 幂等。无 store 或不属于 agent_id 返回 False。"""
        db_path = self._db_path()
        if db_path is None or not await self._item_exists(db_path, item_id, agent_id):
            return False
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE episodes SET protected = 1, updated_at = ? WHERE id = ? AND agent_id = ?",
                (int(time.time()), item_id, agent_id),
            )
            await db.commit()
        logger.info("记忆条目已保护", item_id=item_id, agent_id=agent_id)
        await self._write_audit(db_path, item_id, "protect")
        return True

    async def correct(self, item_id: str, new_content: str, agent_id: str) -> bool:
        """纠正记忆内容 (保留可追溯历史到 memory_revisions)。

        无 store、不属于 agent_id 或条目已 frozen (不再自动更新, 与 delete() 对
        protected 的拒绝方式一致) 时返回 False。new_content 超长时截断
        (见 _MAX_CORRECTED_CONTENT_BYTES), 防止治理接口被当作任意大小文本载体。
        """
        db_path = self._db_path()
        if db_path is None or not await self._item_exists(db_path, item_id, agent_id):
            return False
        revision_id = uuid.uuid4().hex
        now = int(time.time())
        new_content = _truncate_content(new_content)
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT content, frozen FROM episodes WHERE id = ? AND agent_id = ?", (item_id, agent_id)
            )
            row = await cursor.fetchone()
            if row and row[1] == 1:
                logger.info("记忆条目已冻结, 拒绝纠正", item_id=item_id)
                return False
            old_content = row[0] if row else ""
            await db.execute(
                "INSERT INTO memory_revisions (revision_id, item_id, old_content, new_content, corrected_at, reason) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (revision_id, item_id, old_content, new_content, now, "correct"),
            )
            await db.execute(
                "UPDATE episodes SET content = ?, corrected_by = ?, updated_at = ? WHERE id = ? AND agent_id = ?",
                (new_content, revision_id, now, item_id, agent_id),
            )
            await db.commit()
        logger.info("记忆条目已纠正", item_id=item_id, revision_id=revision_id)
        await self._write_audit(db_path, item_id, "correct", detail=f"revision_id={revision_id}")
        return True

    async def delete(self, item_id: str, agent_id: str) -> bool:
        """软删除记忆条目 (deleted=1); protected 条目拒绝。无 store 或不属于 agent_id 返回 False。"""
        db_path = self._db_path()
        if db_path is None or not await self._item_exists(db_path, item_id, agent_id):
            return False
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT protected FROM episodes WHERE id = ? AND agent_id = ?", (item_id, agent_id)
            )
            row = await cursor.fetchone()
            if row and row[0] == 1:
                logger.info("记忆条目受保护, 拒绝删除", item_id=item_id)
                return False
            await db.execute(
                "UPDATE episodes SET deleted = 1, updated_at = ? WHERE id = ? AND agent_id = ?",
                (int(time.time()), item_id, agent_id),
            )
            await db.commit()
        logger.info("记忆条目已软删除", item_id=item_id, agent_id=agent_id)
        await self._write_audit(db_path, item_id, "delete")
        return True

    async def restore(self, item_id: str, agent_id: str) -> bool:
        """恢复被删除/冻结的条目 (反向操作: deleted=0, frozen=0)。无 store 或不属于 agent_id 返回 False。"""
        db_path = self._db_path()
        if db_path is None or not await self._item_exists(db_path, item_id, agent_id):
            return False
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE episodes SET deleted = 0, frozen = 0, updated_at = ? WHERE id = ? AND agent_id = ?",
                (int(time.time()), item_id, agent_id),
            )
            await db.commit()
        logger.info("记忆条目已恢复", item_id=item_id, agent_id=agent_id)
        await self._write_audit(db_path, item_id, "restore")
        return True

    async def export(self, agent_id: str, limit: int = 500, offset: int = 0) -> list[MemoryItem]:
        """导出某 Agent 的记忆 (合规/迁移) 为 list[MemoryItem]。

        N1: 用 MemoryItem.from_episode 适配; 含软删除的条目 (审计保留) 也导出,
        metadata 标记 deleted/frozen/protected。无 store 返回空列表。

        CR2-Fix-15: 此前一次性吐出该 Agent 全部记忆, 记忆量大时是无限量查询;
        加 limit/offset 分页 (默认 limit=500), 配合 offset 翻页取完, 保留
        "含软删除内容也导出"的既有合规/迁移设计不变。
        """
        db_path = self._db_path()
        if db_path is None:
            return []
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM episodes WHERE agent_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?",
                (agent_id, max(1, int(limit)), max(0, int(offset))),
            )
            rows = await cursor.fetchall()
        items: list[MemoryItem] = []
        for row in rows:
            row_dict = {k: row[k] for k in row.keys()}
            item = MemoryItem.from_episode(row_dict)
            item.metadata["frozen"] = int(row_dict.get("frozen", 0) or 0)
            item.metadata["protected"] = int(row_dict.get("protected", 0) or 0)
            item.metadata["deleted"] = int(row_dict.get("deleted", 0) or 0)
            item.metadata["corrected_by"] = row_dict.get("corrected_by") or ""
            items.append(item)
        logger.info("导出 Agent 记忆", agent_id=agent_id, count=len(items))
        return items
