"""多租户数据契约 (O1)。

面向企业化的租户/组织隔离值对象。纯数据、不含行为; 隔离逻辑在 isolation.py。

[框架已搭建 / scaffolding] 契约就位; Agent/记忆/配置/用量按 organization 隔离的真实
执行留待 O1 实现节点。默认单租户 (DEFAULT_TENANT) → 现有单租户行为不变。
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_ORG = "default"
DEFAULT_TENANT = "default"


@dataclass
class TenantContext:
    """一次请求/一个 Agent 所属的租户上下文 (O1)。

    limits 承载租户级配额 (Agent 数 / Token / 存储等), O1 实现节点据此做隔离与限流。
    """

    organization_id: str = DEFAULT_ORG
    tenant_id: str = DEFAULT_TENANT
    limits: dict = field(default_factory=dict)

    @property
    def is_default(self) -> bool:
        """是否为默认单租户 (未启用多租户时的退化态)。"""
        return self.organization_id == DEFAULT_ORG and self.tenant_id == DEFAULT_TENANT
