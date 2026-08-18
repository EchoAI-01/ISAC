"""记忆治理 (N2, MEMORY_DESIGN.md §7)。

L5 实现: freeze/protect/correct/delete/restore/export 六类治理动作真实 SQL + 审计;
correct 保留可追溯历史 (memory_revisions 表); delete 软删除 + protected 拒绝;
restore 反向操作。不动既有 episodes 三表 schema (仅 _ensure_column 加治理列)。
治理是只读后端能力, 可默认开 (governance_enabled=True); 失败不阻塞主链路。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import aiosqlite

from isac.memory.model.memory_item import MemoryItem
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.memory.storage.metadata import MetadataStore
    from isac.memory.storage.sparse import SparseBM25Index

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

    CR3-L3: sparse_resolver 可选注入 (namespace → SparseBM25Index), 让 delete/
    restore/correct 同步内存 BM25 索引 —— 此前软删除只置 deleted=1, 墓碑仍留在
    倒排索引里抬高 total_docs/平均长度, 污染存活项的 IDF 与长度归一。未注入时
    跳过同步 (下次重启 warm_up 已按 deleted=0 过滤, 见 metadata.py)。

    R8: vector_resolver 可选注入 (namespace → VectorStore | None), 让 delete/
    correct/restore 同步稠密向量行 —— 此前软删除只置 deleted=1, 稠密向量行
    残留在 vectors-<ns>.db, 占用 KNN 槽位 + 召回被治理的条目 (search 不
    按 deleted 过滤)。未注入时跳过同步 (主链路 pipeline.search 不依赖
    deleted 标记, 但治理后向量残留仍污染召回)。

    CR3-L5: 各治理操作接受 operator 标识 (控制面 token 指纹/调用方名) 并连同
    agent_id 一起落 memory_audit, 让审计能回答"谁做的"而不只是"发生过"。
    """

    def __init__(
        self,
        metadata_store: MetadataStore | None = None,
        *,
        sparse_resolver: Callable[[str], SparseBM25Index | None] | None = None,
        vector_resolver: Callable[[str], Any] | None = None,
        tenant_guard: Any = None,
        tenant_context: Any = None,
    ) -> None:
        self._store = metadata_store
        self._sparse_resolver = sparse_resolver
        self._vector_resolver = vector_resolver
        # U0 Fix-85: 租户作用域。未显式注入时从所包装的 MetadataStore 读取其
        # _tenant_guard/_tenant_context (生产接线里 store 已带租户上下文, 见 main.py
        # build_services), 让治理 SQL 与检索/写入走同一套租户隔离。此前治理操作直连
        # db_path 裸 SQL 只按 agent_id 过滤, 绕过租户谓词 —— 两租户共享同一 memory.db
        # 时 (见 test_p5 _make_tenanted_pipeline), 租户 A 凭据可对租户 B 的记忆
        # freeze/correct/delete, 是多租户卖点面上的越权实洞。
        self._tenant_guard = (
            tenant_guard if tenant_guard is not None else getattr(metadata_store, "_tenant_guard", None)
        )
        self._tenant_context = (
            tenant_context if tenant_context is not None else getattr(metadata_store, "_tenant_context", None)
        )

    def _db_path(self) -> str | None:
        if self._store is None:
            return None
        return self._store.db_path

    def _tenant_db(self) -> Any | None:
        """U4: 租户机制强制层 (与 MetadataStore 共用同一套原语, 谓词逻辑唯一实现)。

        无 store 时返回 None (各操作已前置 _db_path() 判空)。
        """
        from isac.memory.storage.tenant_bound import TenantBoundDB

        db_path = self._db_path()
        if db_path is None:
            return None
        return TenantBoundDB(
            db_path, tenant_guard=self._tenant_guard, tenant_context=self._tenant_context
        )

    def _tenant_predicate(self) -> tuple[str, list[str]]:
        """U0 Fix-85 / U4: episodes 表 UPDATE/DELETE 的租户谓词片段 + 参数。

        委托 TenantBoundDB.predicate() (唯一实现): 隔离启用且非默认租户时返回
        ``(" AND organization_id = ? AND tenant_id = ?", [org, tenant])``,
        否则 ``("", [])`` —— 与 MetadataStore._tenant_scope/enforce 语义一致
        (默认租户/未启用直通, 零行为变化)。UPDATE/SELECT 的读侧 U4 起改走
        scoped() 子查询包裹; 本方法仅留给无法子查询包裹的 UPDATE 路径。
        """
        tdb = self._tenant_db()
        if tdb is None:
            return "", []
        return tdb.predicate()

    def _sync_sparse(self, agent_id: str, item_id: str, content: str | None) -> None:
        """同步内存 BM25 索引: content=None 表示移除, 否则重建该文档 (CR3-L3)。

        resolver 未注入或该 namespace 无索引时静默跳过; 同步失败只记日志,
        不影响治理操作本身的结果。
        """
        if self._sparse_resolver is None:
            return
        try:
            sparse = self._sparse_resolver(agent_id)
            if sparse is None:
                return
            if content is None:
                sparse.remove(item_id)
            else:
                sparse.add(item_id, content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("BM25 索引同步失败, 已忽略", item_id=item_id, error=str(exc))

    async def _sync_vector_delete(self, agent_id: str, item_id: str) -> None:
        """R8: 同步稠密向量行删除。

        VectorStore.delete(memory_id) 从 vectors-<ns>.db 移除稠密向量。
        resolver 未注入或该 namespace 无 VectorStore 时静默跳过;
        同步失败只记日志, 不影响治理操作本身的结果。
        """
        if self._vector_resolver is None:
            return
        try:
            vector = self._vector_resolver(agent_id)
            if vector is None:
                return
            await vector.delete(item_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("稠密向量同步失败, 已忽略", item_id=item_id, error=str(exc))

    async def _item_exists(self, db_path: str, item_id: str, agent_id: str) -> bool:
        """检查 item 是否存在且属于指定 agent_id (幂等判定 + 跨 Agent 越权拦截)。

        CR2-Fix-11: 此前只按 item_id 判定存在性, 未校验 agent_id, 导致 URL 路径
        里的 {agent_id} 段形同摆设 —— 任何 agent_id 都能操作任意 item_id, 只要
        item 存在。加 agent_id 条件后, item 存在但属于别的 agent 时视为"不存在"
        (幂等语义: 返回 False, 不泄露"item 存在但属于别人"的信息)。

        U0 Fix-85 / U4: 经 TenantBoundDB.scoped() 子查询包裹追加租户作用域 ——
        item 存在但属于别的租户时同样视为"不存在", 拦截跨租户越权。
        """
        tdb = self._tenant_db()
        if tdb is None:
            return False
        query, params = tdb.scoped(
            "SELECT id, organization_id, tenant_id FROM episodes WHERE id = ? AND agent_id = ?",
            [item_id, agent_id],
        )
        async with tdb.connect() as db:
            cursor = await db.execute(query, params)
            return await cursor.fetchone() is not None

    async def _write_audit(
        self,
        db_path: str,
        item_id: str,
        action: str,
        *,
        agent_id: str = "",
        operator: str = "",
        detail: str = "",
    ) -> None:
        """写审计日志 (失败不阻塞主操作)。CR3-L5: 真实落 operator + agent_id;
        U4: 审计行打租户标 (memory_audit 已补租户列)。"""
        tdb = self._tenant_db()
        if tdb is None:
            return
        try:
            organization_id, tenant_id = tdb.row_values()
            async with tdb.connect() as db:
                await db.execute(
                    "INSERT INTO memory_audit "
                    "(audit_id, item_id, action, operator, agent_id, occurred_at, detail, "
                    "organization_id, tenant_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, item_id, action, operator, agent_id, int(time.time()), detail,
                     organization_id, tenant_id),
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("审计日志写入失败, 已忽略", action=action, item_id=item_id, error=str(exc))

    async def list_audit(self, item_id: str) -> list[dict[str, Any]]:
        """读取某条目的审计历史 (供导出/排查)。无 store 时返回空列表。

        U4: 经租户作用域读取 (跨租户审计记录不可见)。
        """
        tdb = self._tenant_db()
        if tdb is None:
            return []
        query, params = tdb.scoped(
            "SELECT audit_id, item_id, action, operator, agent_id, occurred_at, detail, "
            "organization_id, tenant_id "
            "FROM memory_audit WHERE item_id = ? ORDER BY occurred_at ASC",
            [item_id],
        )
        async with tdb.connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
        return [
            {
                "audit_id": r["audit_id"],
                "item_id": r["item_id"],
                "action": r["action"],
                "operator": r["operator"],
                "agent_id": r["agent_id"],
                "occurred_at": r["occurred_at"],
                "detail": r["detail"],
            }
            for r in rows
        ]

    async def freeze(self, item_id: str, agent_id: str, *, operator: str = "") -> bool:
        """冻结记忆条目 (不再自动更新); 幂等。无 store 或不属于 agent_id 返回 False。"""
        db_path = self._db_path()
        tdb = self._tenant_db()
        if db_path is None or tdb is None or not await self._item_exists(db_path, item_id, agent_id):
            return False
        pred, tparams = tdb.predicate()
        async with tdb.connect() as db:
            await db.execute(
                f"UPDATE episodes SET frozen = 1, updated_at = ? WHERE id = ? AND agent_id = ?{pred}",
                (int(time.time()), item_id, agent_id, *tparams),
            )
            await db.commit()
        logger.info("记忆条目已冻结", item_id=item_id, agent_id=agent_id)
        await self._write_audit(db_path, item_id, "freeze", agent_id=agent_id, operator=operator)
        return True

    async def protect(self, item_id: str, agent_id: str, *, operator: str = "") -> bool:
        """保护记忆条目 (不被自动清理/覆盖); 幂等。无 store 或不属于 agent_id 返回 False。"""
        db_path = self._db_path()
        tdb = self._tenant_db()
        if db_path is None or tdb is None or not await self._item_exists(db_path, item_id, agent_id):
            return False
        pred, tparams = tdb.predicate()
        async with tdb.connect() as db:
            await db.execute(
                f"UPDATE episodes SET protected = 1, updated_at = ? WHERE id = ? AND agent_id = ?{pred}",
                (int(time.time()), item_id, agent_id, *tparams),
            )
            await db.commit()
        logger.info("记忆条目已保护", item_id=item_id, agent_id=agent_id)
        await self._write_audit(db_path, item_id, "protect", agent_id=agent_id, operator=operator)
        return True

    async def correct(self, item_id: str, new_content: str, agent_id: str, *, operator: str = "") -> bool:
        """纠正记忆内容 (保留可追溯历史到 memory_revisions)。

        无 store、不属于 agent_id 或条目已 frozen (不再自动更新, 与 delete() 对
        protected 的拒绝方式一致) 时返回 False。new_content 超长时截断
        (见 _MAX_CORRECTED_CONTENT_BYTES), 防止治理接口被当作任意大小文本载体。
        U4: revision 行打租户标。
        """
        db_path = self._db_path()
        tdb = self._tenant_db()
        if db_path is None or tdb is None or not await self._item_exists(db_path, item_id, agent_id):
            return False
        revision_id = uuid.uuid4().hex
        now = int(time.time())
        new_content = _truncate_content(new_content)
        pred, tparams = tdb.predicate()
        organization_id, tenant_id = tdb.row_values()
        read_query, read_params = tdb.scoped(
            "SELECT content, frozen, deleted, organization_id, tenant_id "
            "FROM episodes WHERE id = ? AND agent_id = ?",
            [item_id, agent_id],
        )
        async with tdb.connect() as db:
            cursor = await db.execute(read_query, read_params)
            row = await cursor.fetchone()
            if row and row[1] == 1:
                logger.info("记忆条目已冻结, 拒绝纠正", item_id=item_id)
                return False
            old_content = row[0] if row else ""
            is_deleted = bool(row and row[2] == 1)
            await db.execute(
                "INSERT INTO memory_revisions "
                "(revision_id, item_id, old_content, new_content, corrected_at, reason, "
                "organization_id, tenant_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (revision_id, item_id, old_content, new_content, now, "correct",
                 organization_id, tenant_id),
            )
            await db.execute(
                f"UPDATE episodes SET content = ?, corrected_by = ?, updated_at = ? "
                f"WHERE id = ? AND agent_id = ?{pred}",
                (new_content, revision_id, now, item_id, agent_id, *tparams),
            )
            await db.commit()
        logger.info("记忆条目已纠正", item_id=item_id, revision_id=revision_id)
        # CR3-L3: 纠正后的内容同步进 BM25 内存索引 (add 语义是先 remove 再 add);
        # 软删除条目跳过 —— delete 时已从索引移除, 纠正不应把墓碑重新灌回索引
        # (restore 时才会连内容一起 add 回来)。
        if not is_deleted:
            self._sync_sparse(agent_id, item_id, new_content)
            # R8: 纠正内容后旧向量与新内容不匹配, 直接删除避免旧向量被召回
            # (governor 不知道 embedding, 无法重新 upsert; pipeline 下次
            # store_episode 时会自动 upsert 新向量)
            await self._sync_vector_delete(agent_id, item_id)
        await self._write_audit(
            db_path, item_id, "correct", agent_id=agent_id, operator=operator, detail=f"revision_id={revision_id}"
        )
        return True

    async def delete(self, item_id: str, agent_id: str, *, operator: str = "") -> bool:
        """软删除记忆条目 (deleted=1); protected 条目拒绝。无 store 或不属于 agent_id 返回 False。

        CR3-L3: 成功后同步 sparse.remove(), 让墓碑立即从 BM25 内存索引消失,
        不再污染存活项的 IDF/长度归一 (此前只有重启 warm_up 才能纠正)。
        """
        db_path = self._db_path()
        tdb = self._tenant_db()
        if db_path is None or tdb is None or not await self._item_exists(db_path, item_id, agent_id):
            return False
        pred, tparams = tdb.predicate()
        read_query, read_params = tdb.scoped(
            "SELECT protected, organization_id, tenant_id FROM episodes WHERE id = ? AND agent_id = ?",
            [item_id, agent_id],
        )
        async with tdb.connect() as db:
            cursor = await db.execute(read_query, read_params)
            row = await cursor.fetchone()
            if row and row[0] == 1:
                logger.info("记忆条目受保护, 拒绝删除", item_id=item_id)
                return False
            await db.execute(
                f"UPDATE episodes SET deleted = 1, updated_at = ? WHERE id = ? AND agent_id = ?{pred}",
                (int(time.time()), item_id, agent_id, *tparams),
            )
            await db.commit()
        logger.info("记忆条目已软删除", item_id=item_id, agent_id=agent_id)
        self._sync_sparse(agent_id, item_id, None)
        await self._sync_vector_delete(agent_id, item_id)
        await self._write_audit(db_path, item_id, "delete", agent_id=agent_id, operator=operator)
        return True

    async def restore(self, item_id: str, agent_id: str, *, operator: str = "") -> bool:
        """恢复被删除/冻结的条目 (反向操作: deleted=0, frozen=0)。无 store 或不属于 agent_id 返回 False。

        CR3-L3: 恢复后把内容重新 add 回 BM25 内存索引 (delete 时已 remove)。
        """
        db_path = self._db_path()
        tdb = self._tenant_db()
        if db_path is None or tdb is None or not await self._item_exists(db_path, item_id, agent_id):
            return False
        pred, tparams = tdb.predicate()
        read_query, read_params = tdb.scoped(
            "SELECT content, organization_id, tenant_id FROM episodes WHERE id = ? AND agent_id = ?",
            [item_id, agent_id],
        )
        async with tdb.connect() as db:
            await db.execute(
                f"UPDATE episodes SET deleted = 0, frozen = 0, updated_at = ? WHERE id = ? AND agent_id = ?{pred}",
                (int(time.time()), item_id, agent_id, *tparams),
            )
            cursor = await db.execute(read_query, read_params)
            row = await cursor.fetchone()
            await db.commit()
        logger.info("记忆条目已恢复", item_id=item_id, agent_id=agent_id)
        restored_content = str(row[0]) if row and row[0] else ""
        if restored_content:
            self._sync_sparse(agent_id, item_id, restored_content)
            # R8: restore 后旧向量已不匹配新内容, delete 旧向量避免被召回;
            # 下次 store_episode 会重新 upsert 新向量
            await self._sync_vector_delete(agent_id, item_id)
        await self._write_audit(db_path, item_id, "restore", agent_id=agent_id, operator=operator)
        return True

    async def export(self, agent_id: str, limit: int = 500, offset: int = 0) -> list[MemoryItem]:
        """导出某 Agent 的记忆 (合规/迁移) 为 list[MemoryItem]。

        N1: 用 MemoryItem.from_episode 适配; 含软删除的条目 (审计保留) 也导出,
        metadata 标记 deleted/frozen/protected。无 store 返回空列表。

        CR2-Fix-15: 此前一次性吐出该 Agent 全部记忆, 记忆量大时是无限量查询;
        加 limit/offset 分页 (默认 limit=500), 配合 offset 翻页取完, 保留
        "含软删除内容也导出"的既有合规/迁移设计不变。
        U4: 经 scoped() 子查询包裹 (SELECT * 投影含租户列)。
        """
        tdb = self._tenant_db()
        if tdb is None:
            return []
        query, params = tdb.scoped(
            "SELECT * FROM episodes WHERE agent_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?",
            [agent_id, max(1, int(limit)), max(0, int(offset))],
        )
        async with tdb.connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
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
