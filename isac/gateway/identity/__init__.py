"""跨平台身份归一 (N3, MEMORY_DESIGN.md §3.1)。

[框架已搭建 / scaffolding] PlatformIdentity/PersonIdentity 契约 + IdentityResolver
骨架就位, 组合既有 UserMapper (不改动)。归一算法与持久化留待 N3 实现节点。
业务实现见 DEVELOPMENT_PLAN.md §四 N3。
"""

from __future__ import annotations

from isac.gateway.identity.models import PersonIdentity, PlatformIdentity
from isac.gateway.identity.resolver import IdentityResolver

__all__ = [
    "IdentityResolver",
    "PersonIdentity",
    "PlatformIdentity",
]
