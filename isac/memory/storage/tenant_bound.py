"""U4 TenantBoundDB: 租户机制强制层 —— 租户相关表访问的唯一机制入口。

U4 之前租户隔离靠"调用方自觉": MetadataStore._tenant_scope / MemoryGovernor.
_tenant_predicate 各自维护一份谓词逻辑, consolidator 甚至直连 db_path 裸 SQL
绕过全部机制。U4 把租户读写原语收敛到本层, 调用方只能选用机制原语, 无法自行
拼装谓词:

- ``scoped(query, params)``: SELECT 读查询自动经 enforce() 子查询包裹加租户
  谓词 (CR2-Fix-18 的防 AND/OR 优先级绕过语义在此唯一实现);
- ``predicate()``: UPDATE/DELETE 的规范租户 WHERE 片段 (仅可与 AND-only 的
  原 WHERE 组合, 顶层 AND 追加);
- ``row_values()``: INSERT 行的 organization_id/tenant_id 打标值;
- ``connect()``: 连接入口 (WAL/busy_timeout 由调用方按场景设置)。

鸭子类型持有 guard/context, 不 import runtime 层 (DEVELOP.md 1.2 导入顺序)。
guard 未注入 / disabled / 默认租户时全部原语直通 (单租户零行为变化)。
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

import aiosqlite

# 与 isac.runtime.tenancy.models.DEFAULT_ORG/DEFAULT_TENANT 对齐的字面量
# (不能 import runtime 层, 见 DEVELOP.md 导入顺序)。
_DEFAULT_TENANT_VALUE = "default"


class TenantBoundDB:
    """租户机制强制层 (一个 db_path + guard + context 的访问门面)。"""

    def __init__(
        self,
        db_path: str,
        *,
        tenant_guard: Any = None,
        tenant_context: Any = None,
    ) -> None:
        self.db_path = db_path
        self._guard = tenant_guard
        self._context = tenant_context

    @property
    def guard(self) -> Any:
        return self._guard

    @property
    def context(self) -> Any:
        return self._context

    @property
    def active(self) -> bool:
        """隔离是否实际生效: guard.enabled 且非默认租户 (否则一切原语直通)。"""
        if self._guard is None or self._context is None:
            return False
        if not getattr(self._guard, "enabled", False):
            return False
        return not getattr(self._context, "is_default", True)

    @contextlib.asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """连接入口 (与直连 aiosqlite.connect(db_path) 等价, 语义收口用)。"""
        async with aiosqlite.connect(self.db_path) as db:
            yield db

    def scoped(self, query: str, params: list) -> tuple[str, list]:
        """SELECT 读查询 → 租户作用域 (enforce 子查询包裹); 未生效时原样直通。

        调用约束 (与 TenantIsolationGuard.enforce 一致): 原查询必须投影出
        organization_id/tenant_id 列 (SELECT * 或显式包含), 否则外层 WHERE
        引用不到会报 SQL 错误 —— 机制上强制读查询显式携带租户列。
        """
        if not self.active:
            return query, list(params)
        return self._guard.enforce(query, list(params), self._context)

    def predicate(self) -> tuple[str, list]:
        """UPDATE/DELETE 的租户 WHERE 片段。

        生效时返回 ``(" AND organization_id = ? AND tenant_id = ?", [org, tenant])``,
        否则 ``("", [])``。仅可与 AND-only 的原 WHERE 组合 (顶层 AND 追加不受
        OR 优先级影响; 含 OR 的 WHERE 必须先收敛为子查询再拼)。
        """
        if not self.active:
            return "", []
        return (
            " AND organization_id = ? AND tenant_id = ?",
            [
                str(getattr(self._context, "organization_id", "")),
                str(getattr(self._context, "tenant_id", "")),
            ],
        )

    def row_values(self) -> tuple[str, str]:
        """INSERT 行的 (organization_id, tenant_id) 打标值。

        无论隔离是否生效都按 context 打标 (缺 context 回落 default/default) ——
        默认租户行也带 default 标, 与既有 episodes 写入口径一致, 升级多租户时
        存量行不需要回填。
        """
        if self._context is None:
            return (_DEFAULT_TENANT_VALUE, _DEFAULT_TENANT_VALUE)
        return (
            str(getattr(self._context, "organization_id", _DEFAULT_TENANT_VALUE)),
            str(getattr(self._context, "tenant_id", _DEFAULT_TENANT_VALUE)),
        )
