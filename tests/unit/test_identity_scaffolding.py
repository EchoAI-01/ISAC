"""N3 身份归一骨架测试 (L5 已实现后的回归)。

验证 PlatformIdentity/PersonIdentity 契约默认值, 以及 IdentityResolver 组合既有
UserMapper 的行为 (resolve 委托 / bind 落表 / merge 合并 / arbitrate_conflict
按 confidence 排序)。本文件覆盖骨架级回归, 详细业务测试在
test_identity_resolver.py。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

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


@pytest.mark.asyncio
async def test_resolver_delegates_to_user_mapper() -> None:
    """有 UserMapper 时 resolve 委托 UserMapper 创建新 person (verified 未命中场景)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    tmp_path = tmp.name
    try:
        mapper = UserMapper()
        resolver = IdentityResolver(mapper, db_path=tmp_path)
        person_id = await resolver.resolve("qq", "12345", nickname="小明")
        # 未命中 verified → 委托 UserMapper.resolve → 返回新 master_id
        assert person_id is not None
        profile = await mapper.resolve("qq", "12345")
        assert person_id == profile.user_id
    finally:
        import asyncio

        await asyncio.to_thread(lambda: Path(tmp_path).unlink(missing_ok=True))


@pytest.mark.asyncio
async def test_resolver_without_mapper_returns_none_for_resolve() -> None:
    """无 UserMapper 且 verified 未命中时 resolve 返回 None (不委托)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    tmp_path = tmp.name
    try:
        resolver = IdentityResolver(None, db_path=tmp_path)
        assert await resolver.resolve("qq", "12345") is None
    finally:
        import asyncio

        await asyncio.to_thread(lambda: Path(tmp_path).unlink(missing_ok=True))


def test_resolver_merge_combines_aliases_and_accounts() -> None:
    """merge 合并 aliases/platform_accounts, confidence 取较低, verified 取 AND."""
    resolver = IdentityResolver(None, db_path=":memory:")
    a = PersonIdentity(
        person_id="p1",
        aliases=["张三"],
        platform_accounts=[PlatformIdentity(platform="qq", connection_id="c1", platform_user_id="u1")],
        verified=True,
        confidence=1.0,
    )
    b = PersonIdentity(
        person_id="p2",
        aliases=["李四"],
        platform_accounts=[PlatformIdentity(platform="tg", connection_id="c2", platform_user_id="u2")],
        verified=False,
        confidence=0.5,
    )
    merged = resolver.merge(a, b)
    assert merged.person_id == "p1"
    assert "张三" in merged.aliases and "李四" in merged.aliases
    assert len(merged.platform_accounts) == 2
    assert merged.confidence == 0.5
    assert merged.verified is False


def test_resolver_arbitrate_conflict_returns_highest() -> None:
    """arbitrate_conflict 按 confidence 降序取最高者."""
    resolver = IdentityResolver(None, db_path=":memory:")
    a = PersonIdentity(person_id="p1", confidence=0.3)
    b = PersonIdentity(person_id="p2", confidence=0.9)
    winner = resolver.arbitrate_conflict([a, b])
    assert winner is not None
    assert winner.person_id == "p2"
    assert resolver.arbitrate_conflict([]) is None
