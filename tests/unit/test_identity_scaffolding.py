"""N3 身份归一骨架测试。

验证 PlatformIdentity/PersonIdentity 契约默认值,以及 IdentityResolver 组合既有
UserMapper 的骨架行为 (委托 resolve/bind, merge/arbitrate 安全默认)。真实归一算法
属实现节点 (N3), 本文件只覆盖骨架级行为。
"""

from __future__ import annotations

from isac.gateway.identity import IdentityResolver, PersonIdentity, PlatformIdentity
from isac.gateway.user_mapper import UserMapper


def test_platform_identity_defaults() -> None:
    pid = PlatformIdentity(platform="qq", connection_id="c1", platform_user_id="u1")
    assert pid.display_name == ""
    assert pid.group_aliases == {}


def test_person_identity_defaults() -> None:
    person = PersonIdentity(person_id="p1")
    assert person.aliases == []
    assert person.platform_accounts == []
    assert person.verified is False
    assert person.confidence == 1.0


async def test_resolver_delegates_to_user_mapper() -> None:
    mapper = UserMapper()
    resolver = IdentityResolver(mapper)
    person_id = await resolver.resolve("qq", "12345", nickname="小明")
    # 委托 UserMapper.resolve → 返回其 master_id (骨架阶段等价于现有映射)
    assert person_id is not None
    profile = await mapper.resolve("qq", "12345")
    assert person_id == profile.user_id


async def test_resolver_without_mapper_returns_none() -> None:
    resolver = IdentityResolver(None)
    assert await resolver.resolve("qq", "12345") is None
    assert await resolver.bind("p1", PlatformIdentity("qq", "c1", "u1")) is False


def test_resolver_merge_and_arbitrate_safe_defaults() -> None:
    resolver = IdentityResolver()
    a = PersonIdentity(person_id="p1")
    b = PersonIdentity(person_id="p2")
    assert resolver.merge(a, b) is a  # 骨架: 返回 primary 不变
    assert resolver.arbitrate_conflict([a, b]) is a
    assert resolver.arbitrate_conflict([]) is None
