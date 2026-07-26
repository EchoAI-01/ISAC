"""TenantIsolationGuard: 租户隔离 (O1, ROUTING_AND_AGENT_MESH.md §6 + 企业化需求)。

O1 实现: namespace_for enabled 时给记忆/存储命名空间加 org:tenant:base 前缀
(默认租户直通); check_access enabled 时跨租户不可见 (resource_org != tenant.org
且 != DEFAULT 拒绝); enforce 给 SQL 查询注入 tenant_id 谓词 (WHERE 已有时追加
AND tenant_id = ?, 无 WHERE 时加 WHERE tenant_id = ?); assert_visible 跨租户
不可见抛 PermissionError。默认 enabled=False (单租户 passthrough, 零行为变化)。
"""

from __future__ import annotations

import re

from isac.runtime.tenancy.models import DEFAULT_ORG, TenantContext
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class TenantIsolationGuard:
    """租户隔离守卫 (默认单租户直通, enabled=True 时严格隔离)。"""

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled

    def namespace_for(self, base_namespace: str, tenant: TenantContext) -> str:
        """给记忆/存储命名空间加租户前缀。

        O1: enabled 且非默认租户时返回 f"{org}:{tenant}:{base}"; 否则原样返回。
        """
        if not self.enabled or tenant.is_default:
            return base_namespace
        return f"{tenant.organization_id}:{tenant.tenant_id}:{base_namespace}"

    def check_access(self, resource_org: str, tenant: TenantContext) -> bool:
        """校验某租户能否访问某组织的资源 (跨租户不可见)。

        O1: disabled 恒放行; enabled 时 resource_org == tenant.org 或 == DEFAULT
        (全局共享) 才允许。
        """
        if not self.enabled:
            return True
        return resource_org in (tenant.organization_id, DEFAULT_ORG)

    def assert_visible(self, resource_org: str, tenant: TenantContext) -> None:
        """断言资源可见, 不可见抛 PermissionError (供数据面调用)."""
        if not self.check_access(resource_org, tenant):
            logger.warning(
                "跨租户访问被拒绝",
                resource_org=resource_org,
                tenant_org=tenant.organization_id,
                tenant_id=tenant.tenant_id,
            )
            raise PermissionError(
                f"租户 {tenant.organization_id}/{tenant.tenant_id} 无权访问组织 {resource_org} 的资源"
            )

    def enforce(
        self,
        query: str,
        params: list,
        table: str,
        tenant: TenantContext,
    ) -> tuple[str, list]:
        """给 SQL 查询注入 tenant_id 谓词 (WHERE 已有时追加 AND, 无 WHERE 时加 WHERE)。

        O1: disabled 或默认租户时原样返回; 否则在查询中找到 WHERE 子句追加
        AND organization_id = ? AND tenant_id = ?, 或无 WHERE 时直接 WHERE。
        params 顺序: [原 params..., org, tenant_id]。
        """
        if not self.enabled or tenant.is_default:
            return query, params
        # 用正则匹配 WHERE (大小写不敏感, 词边界), 避免误匹配列名
        where_match = re.search(r"\bWHERE\b", query, re.IGNORECASE)
        if where_match:
            # 在 WHERE 之后追加 AND 谓词
            insert_pos = where_match.end()
            new_query = (
                query[:insert_pos]
                + " organization_id = ? AND tenant_id = ? AND"
                + query[insert_pos:]
            )
        else:
            # 无 WHERE: 在表名后追加 WHERE (匹配 FROM <table>)
            from_match = re.search(rf"\bFROM\s+{re.escape(table)}\b", query, re.IGNORECASE)
            if from_match:
                insert_pos = from_match.end()
                new_query = (
                    query[:insert_pos]
                    + " WHERE organization_id = ? AND tenant_id = ?"
                    + query[insert_pos:]
                )
            else:
                # 兜底: 直接在末尾追加 WHERE (不期望走到, 防御性)
                new_query = query + " WHERE organization_id = ? AND tenant_id = ?"
        new_params = list(params) + [tenant.organization_id, tenant.tenant_id]
        return new_query, new_params
