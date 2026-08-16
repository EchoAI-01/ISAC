"""TenantManager: 租户 CRUD + 成员管理 (R6-①, SQLite 持久化)。

数据面隔离已在 MetadataStore 层由 TenantIsolationGuard 完成 (guard.enforce 跨租户
互不可见); R6 控制面落地租户资源的 CRUD 入口 —— 创建/列出/删除租户, 管理租户成员
(用户/Agent 归属)。照 UserMapper/SessionManager SQLite 持久化同构: 惰性建表 +
best-effort 写穿 + 重启恢复。不传 db_path 时纯内存 (测试零行为变化)。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from isac.utils.helpers import new_id, unix_now
from isac.utils.logger import get_logger

logger = get_logger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL DEFAULT 'default',
    display_name TEXT,
    created_at INTEGER,
    state TEXT DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_tenants_org ON tenants(organization_id);
CREATE TABLE IF NOT EXISTS tenant_members (
    tenant_id TEXT NOT NULL,
    member_id TEXT NOT NULL,
    member_type TEXT DEFAULT 'user',
    created_at INTEGER,
    PRIMARY KEY (tenant_id, member_id, member_type)
);
"""


@dataclass
class Tenant:
    """租户资源 (R6 控制面 CRUD 对象)。"""

    tenant_id: str
    organization_id: str = "default"
    display_name: str = ""
    created_at: int = 0
    state: str = "active"
    members: list[dict[str, Any]] = field(default_factory=list)


class TenantManager:
    """租户管理器 (内存缓存 + 可选 SQLite 写穿持久化)。"""

    def __init__(self, db_path: str | None = None) -> None:
        self._tenants: dict[str, Tenant] = {}
        self._db_path = db_path
        self._schema_ready = False
        self._lock = asyncio.Lock()

    async def create(
        self, tenant_id: str | None = None, *, organization_id: str = "default",
        display_name: str = "",
    ) -> Tenant:
        """创建租户。tenant_id 为空时自动生成。已存在抛 ValueError。"""
        async with self._lock:
            tid = tenant_id or new_id("tenant")
            if tid in self._tenants or await self._exists_in_db(tid):
                raise ValueError(f"租户已存在: {tid}")
            tenant = Tenant(
                tenant_id=tid, organization_id=organization_id,
                display_name=display_name or tid, created_at=unix_now(),
            )
            self._tenants[tid] = tenant
            await self._persist(tenant)
            logger.info("租户已创建", tenant_id=tid, organization_id=organization_id)
            return tenant

    async def get(self, tenant_id: str) -> Tenant | None:
        async with self._lock:
            tenant = self._tenants.get(tenant_id)
            if tenant is None and self._db_path is not None:
                tenant = await self._load_from_db(tenant_id)
            return tenant

    async def list_tenants(self, *, organization_id: str | None = None) -> list[Tenant]:
        """列出租户 (可选按 organization 过滤)。先内存, 缺失补库 (全量重建)。"""
        async with self._lock:
            if self._db_path is not None and not self._tenants:
                await self._load_all_from_db()
            tenants = list(self._tenants.values())
        if organization_id:
            tenants = [t for t in tenants if t.organization_id == organization_id]
        return tenants

    async def delete(self, tenant_id: str) -> bool:
        """删除租户 + 其成员。不存在返回 False。"""
        async with self._lock:
            existed = self._tenants.pop(tenant_id, None) is not None
            if self._db_path is not None:
                # 内存未命中时查库确认 (重启后内存为空, 仅库有)
                if not existed:
                    existed = await self._exists_in_db(tenant_id)
                if existed:
                    await self._delete_from_db(tenant_id)
            if existed:
                logger.info("租户已删除", tenant_id=tenant_id)
            return existed

    async def add_member(self, tenant_id: str, member_id: str, *, member_type: str = "user") -> None:
        """添加成员到租户。租户不存在抛 ValueError。"""
        async with self._lock:
            tenant = self._tenants.get(tenant_id)
            if tenant is None and self._db_path is not None:
                tenant = await self._load_from_db(tenant_id)
            if tenant is None:
                raise ValueError(f"租户不存在: {tenant_id}")
            entry = {"member_id": member_id, "member_type": member_type, "created_at": unix_now()}
            if not any(m["member_id"] == member_id and m["member_type"] == member_type for m in tenant.members):
                tenant.members.append(entry)
                await self._persist_member(tenant_id, entry)
                logger.info("租户成员已添加", tenant_id=tenant_id, member_id=member_id)

    async def remove_member(self, tenant_id: str, member_id: str, *, member_type: str = "user") -> bool:
        """移除成员。返回是否移除成功。"""
        async with self._lock:
            tenant = self._tenants.get(tenant_id)
            if tenant is None and self._db_path is not None:
                tenant = await self._load_from_db(tenant_id)
            if tenant is None:
                return False
            before = len(tenant.members)
            tenant.members = [
                m for m in tenant.members
                if not (m["member_id"] == member_id and m["member_type"] == member_type)
            ]
            removed = before > len(tenant.members)
            if removed and self._db_path is not None:
                await self._delete_member_from_db(tenant_id, member_id, member_type)
            return removed

    # ── SQLite 持久化 (照 UserMapper/SessionManager 同构) ──────────

    async def _ensure_schema(self) -> None:
        if self._db_path is None or self._schema_ready:
            return
        import aiosqlite

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await db.commit()
        self._schema_ready = True
        logger.info("TenantManager 持久化已初始化", path=self._db_path)

    async def _exists_in_db(self, tenant_id: str) -> bool:
        if self._db_path is None:
            return False
        try:
            await self._ensure_schema()
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                cur = await db.execute("SELECT 1 FROM tenants WHERE tenant_id = ?", (tenant_id,))
                return (await cur.fetchone()) is not None
        except Exception as exc:  # noqa: BLE001
            logger.warning("TenantManager 存在性查询失败", error=str(exc))
            return False

    async def _load_from_db(self, tenant_id: str) -> Tenant | None:
        if self._db_path is None:
            return None
        try:
            await self._ensure_schema()
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                cur = await db.execute(
                    "SELECT tenant_id, organization_id, display_name, created_at, state "
                    "FROM tenants WHERE tenant_id = ?",
                    (tenant_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return None
                tenant = Tenant(
                    tenant_id=str(row[0]), organization_id=str(row[1] or "default"),
                    display_name=str(row[2] or ""), created_at=int(row[3] or 0),
                    state=str(row[4] or "active"),
                )
                tenant.members = await self._load_members(db, tenant_id)
            self._tenants[tenant_id] = tenant
            return tenant
        except Exception as exc:  # noqa: BLE001
            logger.warning("TenantManager 读取失败", tenant_id=tenant_id, error=str(exc))
            return None

    async def _load_all_from_db(self) -> None:
        """全量重建内存缓存 (重启恢复; 仅 list_tenants 缓存为空时触发)。"""
        if self._db_path is None:
            return
        try:
            await self._ensure_schema()
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                cur = await db.execute(
                    "SELECT tenant_id, organization_id, display_name, created_at, state FROM tenants"
                )
                for row in await cur.fetchall():
                    tid = str(row[0])
                    tenant = Tenant(
                        tenant_id=tid, organization_id=str(row[1] or "default"),
                        display_name=str(row[2] or ""), created_at=int(row[3] or 0),
                        state=str(row[4] or "active"),
                    )
                    tenant.members = await self._load_members(db, tid)
                    self._tenants[tid] = tenant
        except Exception as exc:  # noqa: BLE001
            logger.warning("TenantManager 全量加载失败", error=str(exc))

    async def _load_members(self, db: Any, tenant_id: str) -> list[dict[str, Any]]:
        cur = await db.execute(
            "SELECT member_id, member_type, created_at FROM tenant_members WHERE tenant_id = ?",
            (tenant_id,),
        )
        return [
            {"member_id": str(r[0]), "member_type": str(r[1]), "created_at": int(r[2] or 0)}
            for r in await cur.fetchall()
        ]

    async def _persist(self, tenant: Tenant) -> None:
        if self._db_path is None:
            return
        try:
            await self._ensure_schema()
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO tenants "
                    "(tenant_id, organization_id, display_name, created_at, state) VALUES (?, ?, ?, ?, ?)",
                    (tenant.tenant_id, tenant.organization_id, tenant.display_name,
                     tenant.created_at, tenant.state),
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("TenantManager 写入失败", error=str(exc))

    async def _persist_member(self, tenant_id: str, entry: dict[str, Any]) -> None:
        if self._db_path is None:
            return
        try:
            await self._ensure_schema()
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT OR IGNORE INTO tenant_members (tenant_id, member_id, member_type, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (tenant_id, entry["member_id"], entry["member_type"], entry["created_at"]),
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("TenantManager 成员写入失败", error=str(exc))

    async def _delete_member_from_db(self, tenant_id: str, member_id: str, member_type: str) -> None:
        if self._db_path is None:
            return
        try:
            await self._ensure_schema()
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "DELETE FROM tenant_members WHERE tenant_id = ? AND member_id = ? AND member_type = ?",
                    (tenant_id, member_id, member_type),
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("TenantManager 成员删除失败", error=str(exc))

    async def _delete_from_db(self, tenant_id: str) -> None:
        if self._db_path is None:
            return
        try:
            await self._ensure_schema()
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("DELETE FROM tenants WHERE tenant_id = ?", (tenant_id,))
                await db.execute("DELETE FROM tenant_members WHERE tenant_id = ?", (tenant_id,))
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("TenantManager 删除失败", error=str(exc))
