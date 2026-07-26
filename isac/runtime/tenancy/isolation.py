"""TenantIsolationGuard: 租户隔离 (O1, ROUTING_AND_AGENT_MESH.md §6 + 企业化需求)。

O1 实现: namespace_for enabled 时给记忆/存储命名空间加 org:tenant:base 前缀
(默认租户直通); check_access enabled 时跨租户不可见 (resource_org != tenant.org
且 != DEFAULT 拒绝); enforce 用子查询包裹整个原查询, 外层加
WHERE organization_id = ? AND tenant_id = ? (CR2-Fix-18: 不拼进内层 WHERE
表达式, 不受原查询 AND/OR 组合方式影响); assert_visible 跨租户不可见抛
PermissionError。默认 enabled=False (单租户 passthrough, 零行为变化)。
"""

from __future__ import annotations

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
        tenant: TenantContext,
    ) -> tuple[str, list]:
        """给 SQL 查询注入 tenant_id 谓词 (用子查询包裹整个原查询)。

        O1: disabled 或默认租户时原样返回; 否则用子查询包裹整个原查询, 外层
        加 WHERE organization_id = ? AND tenant_id = ?。

        CR2-Fix-18: 此前直接在原查询的 WHERE 后拼接 AND organization_id = ?
        AND tenant_id = ? AND, 对含顶层 OR 的查询会被操作符优先级绕过 (真实
        sqlite3 验证: `WHERE agent_id=? OR is_shared=1` 拼接后变成
        `WHERE org=? AND tenant=? AND agent_id=? OR is_shared=1`, AND 优先级
        高于 OR, 任何 is_shared=1 的行都绕过租户过滤, 与查询实际所属租户无关)。
        子查询包裹的租户谓词作用于内层查询的输出行, 不拼进内层 WHERE 表达式,
        天然不受内层 AND/OR 组合方式影响; SQLite 对子查询套 ORDER BY/LIMIT
        完全支持, 也不再需要识别原查询的 FROM 表名 (故去掉此前的 table 参数)。

        调用约束: 原查询必须投影出 organization_id/tenant_id 列 (即
        SELECT * 或显式包含这两列), 否则外层 WHERE 引用不到会报 SQL 错误;
        本项目 metadata.py 里的查询一律 SELECT *, 天然满足。

        params 顺序: [原 params..., org, tenant_id]。
        """
        if not self.enabled or tenant.is_default:
            return query, params
        new_query = f"SELECT * FROM ({query}) AS _tenant_scoped WHERE organization_id = ? AND tenant_id = ?"
        new_params = list(params) + [tenant.organization_id, tenant.tenant_id]
        return new_query, new_params
