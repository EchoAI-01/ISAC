"""多租户与组织隔离 (O1 企业化)。

[框架已搭建 / scaffolding] TenantContext 契约 + TenantIsolationGuard 骨架就位,
默认单租户 passthrough, 主链路零行为变化。真实隔离与限流见 DEVELOPMENT_PLAN.md §四 O1。
"""

from __future__ import annotations

from isac.runtime.tenancy.isolation import TenantIsolationGuard
from isac.runtime.tenancy.models import DEFAULT_ORG, DEFAULT_TENANT, TenantContext

__all__ = [
    "DEFAULT_ORG",
    "DEFAULT_TENANT",
    "TenantContext",
    "TenantIsolationGuard",
]
