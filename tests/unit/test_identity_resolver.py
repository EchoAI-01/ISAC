"""N3 身份归一业务测试。

覆盖:
- IdentityResolver.resolve: verified 直接返回 person_id
- IdentityResolver.resolve: 未命中走启发式 (nickname 匹配) → confidence<1.0
- IdentityResolver.bind: 写 person_identities 表 + verified=1/confidence=1.0
- IdentityResolver.merge: 合并 aliases/platform_accounts; confidence 取较低; verified 取 AND
- IdentityResolver.arbitrate_conflict: 按 confidence 排序, 低置信写 identity_conflicts
- heuristic_enabled=False 时只走 verified 路径 (不启发式合并)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from isac.gateway.identity.models import PersonIdentity, PlatformIdentity
from isac.gateway.identity.resolver import IdentityResolver
from isac.gateway.user_mapper import UserMapper


@pytest.fixture
async def resolver() -> IdentityResolver:
    """构造内存级 UserMapper + IdentityResolver fixture (用临时 db 路径)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    tmp_path = tmp.name
    mapper = UserMapper()
    r = IdentityResolver(mapper, heuristic_enabled=True, db_path=tmp_path)
    yield r
    import asyncio

    await asyncio.to_thread(lambda: Path(tmp_path).unlink(missing_ok=True))


# ── resolve ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_verified_returns_person_id(resolver: IdentityResolver) -> None:
    """已 bind 的 (platform, user_id) 直接返回 person_id (verified)."""
    identity = PlatformIdentity(
        platform="qq",
        connection_id="c1",
        platform_user_id="u1",
        display_name="张三",
    )
    await resolver.bind("p1", identity)
    result = await resolver.resolve("qq", "u1", "张三")
    assert result == "p1"


@pytest.mark.asyncio
async def test_resolve_unverified_heuristic_matches_nickname(resolver: IdentityResolver) -> None:
    """未 bind 的 (platform, user_id) 走启发式: nickname 与已有 person 匹配 → confidence<1.0."""
    identity = PlatformIdentity(
        platform="qq",
        connection_id="c1",
        platform_user_id="u1",
        display_name="李四",
    )
    await resolver.bind("p1", identity)
    # 不同平台、相同 nickname → 启发式匹配为同一人 (confidence<1.0)
    result = await resolver.resolve("telegram", "u2", "李四")
    assert result == "p1"  # 启发式合并到 p1


@pytest.mark.asyncio
async def test_resolve_no_match_returns_new_person(resolver: IdentityResolver) -> None:
    """无任何匹配时创建新 person_id (UserMapper.resolve 兜底)."""
    result = await resolver.resolve("discord", "u3", "新用户")
    assert result is not None
    assert result.startswith("user_")  # UserMapper 创建的新 master_id


@pytest.mark.asyncio
async def test_resolve_heuristic_disabled_only_uses_verified(resolver: IdentityResolver) -> None:
    """heuristic_enabled=False 时只走 verified 路径, 不启发式合并."""
    resolver.heuristic_enabled = False
    identity = PlatformIdentity(
        platform="qq",
        connection_id="c1",
        platform_user_id="u1",
        display_name="王五",
    )
    await resolver.bind("p1", identity)
    # 不同平台相同 nickname: 启发式关闭, 不合并, 创建新 person
    result = await resolver.resolve("telegram", "u2", "王五")
    assert result != "p1"  # 不启发式合并
    assert result is not None


@pytest.mark.asyncio
async def test_resolve_does_not_treat_unverified_row_as_verified_hit(resolver: IdentityResolver) -> None:
    """CR2-Fix-17: resolve() 步骤 1 此前没有 verified=1 条件, 任何 verified 值的行
    都被当作"verified 命中"直接返回, 与该步骤自己的注释"1. verified 命中"矛盾。"""
    # 直接写入一条 verified=0 的低置信度记录 (模拟一次不可靠的历史启发式匹配)
    await resolver._ensure_schema()
    await resolver._write_identity_row(
        person_id="p_low_confidence",
        platform="qq",
        platform_user_id="u9",
        display_name="旧昵称",
        verified=0,
        confidence=0.3,
        source="heuristic",
    )
    resolver.heuristic_enabled = False  # 隔离变量: 命中只能来自步骤 1, 不受步骤 2 影响

    result = await resolver.resolve("qq", "u9", "新昵称")

    # 修复前: 步骤 1 不检查 verified, 直接把这条 verified=0 的行当"验证命中"返回。
    # 修复后: 步骤 1 查不到 (verified != 1), 启发式已关闭, 落到步骤 3 UserMapper
    # 兜底创建新 person —— 不应是那条未验证记录的 person_id。
    assert result != "p_low_confidence"


# ── bind ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bind_writes_verified_identity(resolver: IdentityResolver) -> None:
    """bind 写 person_identities 表, verified=1, confidence=1.0, source=manual."""
    identity = PlatformIdentity(
        platform="qq",
        connection_id="c1",
        platform_user_id="u1",
        display_name="赵六",
    )
    assert await resolver.bind("p1", identity) is True
    # 二次 bind 同一 (platform, user_id) 应幂等更新
    assert await resolver.bind("p1", identity) is True


@pytest.mark.asyncio
async def test_bind_without_mapper_still_writes_identity_table() -> None:
    """无 UserMapper 时 bind 仍落 person_identities 表 (供 arbitrate_conflict 测试)."""
    import tempfile
    from pathlib import Path

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    tmp_path = tmp.name
    try:
        r = IdentityResolver(None, db_path=tmp_path)
        identity = PlatformIdentity(
            platform="qq", connection_id="c1", platform_user_id="u1", display_name="赵六"
        )
        assert await r.bind("p1", identity) is True
        # resolve 查 verified 命中 (即使无 UserMapper)
        result = await r.resolve("qq", "u1", "赵六")
        assert result == "p1"
    finally:
        import asyncio

        await asyncio.to_thread(lambda: Path(tmp_path).unlink(missing_ok=True))


# ── merge ───────────────────────────────────────────────────────


def test_merge_combines_aliases_and_accounts() -> None:
    """合并两个 PersonIdentity: aliases/platform_accounts 取并集."""
    r = IdentityResolver(None)
    p1 = PersonIdentity(
        person_id="p1",
        aliases=["张三", "老张"],
        platform_accounts=[
            PlatformIdentity(platform="qq", connection_id="c1", platform_user_id="u1"),
        ],
        verified=True,
        confidence=1.0,
    )
    p2 = PersonIdentity(
        person_id="p2",
        aliases=["张三", "Zhang San"],
        platform_accounts=[
            PlatformIdentity(platform="telegram", connection_id="c2", platform_user_id="u2"),
        ],
        verified=False,
        confidence=0.6,
    )
    merged = r.merge(p1, p2)
    assert "张三" in merged.aliases
    assert "老张" in merged.aliases
    assert "Zhang San" in merged.aliases
    assert len(merged.platform_accounts) == 2
    # confidence 取较低者
    assert merged.confidence == 0.6
    # verified 取 AND (任一未验证则未验证)
    assert merged.verified is False


def test_merge_preserves_primary_person_id() -> None:
    """合并后保留 primary 的 person_id."""
    r = IdentityResolver(None)
    p1 = PersonIdentity(person_id="p1", confidence=1.0)
    p2 = PersonIdentity(person_id="p2", confidence=0.5)
    merged = r.merge(p1, p2)
    assert merged.person_id == "p1"


# ── arbitrate_conflict ──────────────────────────────────────────


def test_arbitrate_conflict_returns_highest_confidence() -> None:
    """多个候选时按 confidence 降序, 取最高者."""
    r = IdentityResolver(None)
    candidates = [
        PersonIdentity(person_id="p1", confidence=0.5),
        PersonIdentity(person_id="p2", confidence=0.9, verified=True),
        PersonIdentity(person_id="p3", confidence=0.7),
    ]
    winner = r.arbitrate_conflict(candidates)
    assert winner is not None
    assert winner.person_id == "p2"  # confidence 0.9 最高


def test_arbitrate_conflict_empty_returns_none() -> None:
    r = IdentityResolver(None)
    assert r.arbitrate_conflict([]) is None


def test_arbitrate_conflict_low_confidence_writes_conflict_record() -> None:
    """最高 confidence < 0.7 时写入 identity_conflicts 表供人工裁决."""
    import os
    import tempfile
    from pathlib import Path

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    tmp_path = tmp.name
    try:
        r = IdentityResolver(None, db_path=tmp_path)
        candidates = [
            PersonIdentity(person_id="p1", confidence=0.4),
            PersonIdentity(person_id="p2", confidence=0.5),  # 最高, 但 < 0.7
        ]
        winner = r.arbitrate_conflict(candidates)
        # 仍返回最高者, 但标记为低置信
        assert winner is not None
        assert winner.person_id == "p2"
        # identity_conflicts 表应有记录
        conflicts = r.list_conflicts()
        assert len(conflicts) >= 1
        assert conflicts[0]["person_id"] == "p2"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        _ = Path  # 避免 ruff unused import
