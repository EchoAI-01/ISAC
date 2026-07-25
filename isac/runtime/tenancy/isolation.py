"""TenantIsolationGuard: 租户隔离骨架 (O1)。

[框架已搭建 / scaffolding] 校验跨租户访问、给命名空间加租户前缀的挂接点就位;真正的
Agent/记忆/配置/用量隔离与租户级鉴权留待 O1 实现节点 (见 TODO)。默认单租户
passthrough: 不加前缀、不拦截, 主链路零行为变化。
"""

from __future__ import annotations

from isac.runtime.tenancy.models import DEFAULT_ORG, TenantContext
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class TenantIsolationGuard:
    """租户隔离守卫 (骨架, 默认单租户直通)。"""

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled

    def namespace_for(self, base_namespace: str, tenant: TenantContext) -> str:
        """给记忆/存储命名空间加租户前缀。

        TODO(O1): enabled 时返回 f"{org}:{tenant}:{base}"; 骨架/未启用时原样返回,
        与现有全局命名空间行为一致。
        """
        if not self.enabled or tenant.is_default:
            return base_namespace
        return f"{tenant.organization_id}:{tenant.tenant_id}:{base_namespace}"

    def check_access(self, resource_org: str, tenant: TenantContext) -> bool:
        """校验某租户能否访问某组织的资源 (跨租户不可见)。

        TODO(O1): enabled 时严格比对 org 并接入控制面鉴权; 骨架/未启用时恒放行。
        """
        if not self.enabled:
            return True
        return resource_org in (tenant.organization_id, DEFAULT_ORG)
