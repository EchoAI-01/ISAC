"""L5 (2026-10-13 review): 身份归一层生产接线测试 (08-19/08-21 遗留⑤)。

覆盖三个修复点:
- P1-1: resolve() 启发式路径经 arbitrate_conflict 生产接线 (此前该入口零生产
  调用, identity_conflicts 表恒空);
- P0-2: 昵称撞名不自动归属 —— 证据置信度封顶 0.5 (< 0.7 阈值), 攻击者改昵称
  无法让其消息归入既有 person 的记忆/画像 (此前撞名直接返回匹配者);
- P1-2: 人工裁决回写 —— 冲突记录带触发身份坐标, 裁决后所选 person 以 verified
  绑定落表, 后续 resolve 直接受益 (此前只改 conflicts 行, 归一行为不变)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from isac.gateway.identity.models import PersonIdentity, PlatformIdentity
from isac.gateway.identity.resolver import (
    CONFLICT_THRESHOLD,
    NICKNAME_MATCH_CONFIDENCE_CAP,
    IdentityResolver,
)


def _resolver(tmp_path: Path, *, heuristic: bool = True) -> IdentityResolver:
    return IdentityResolver(
        None, heuristic_enabled=heuristic, db_path=str(tmp_path / "identity.db")
    )


async def _bind_verified(
    resolver: IdentityResolver, person_id: str, platform: str, user_id: str, name: str
) -> None:
    await resolver.bind(
        person_id,
        PlatformIdentity(platform=platform, connection_id="", platform_user_id=user_id, display_name=name),
    )


@pytest.mark.asyncio
async def test_p0_2_nickname_collision_never_attributes(tmp_path: Path) -> None:
    """昵称撞名防冒充: 受害者 verified 绑定昵称"小明"; 陌生人在另一平台改昵称
    "小明" → resolve 不得返回受害者的 person_id (走新人/None fail-safe),
    且候选入冲突队列。"""
    resolver = _resolver(tmp_path)
    await _bind_verified(resolver, "person_victim", "qq", "10001", "小明")

    # 攻击者: telegram 平台, 昵称撞名 (无 mapper → 新人路径返回 None)。
    result = await resolver.resolve("telegram", "attacker-1", "小明")
    assert result != "person_victim"
    assert result is None  # 无 UserMapper 兜底创建新人 → None (不归属他人)

    # 同平台撞名同样不归属 (攻击者在受害者所在平台注册新号)。
    result2 = await resolver.resolve("qq", "attacker-2", "小明")
    assert result2 != "person_victim"


@pytest.mark.asyncio
async def test_p1_1_heuristic_path_records_conflict_with_trigger(tmp_path: Path) -> None:
    """P1-1 生产接线: 启发式路径写 identity_conflicts (带触发坐标) —— 此前
    arbitrate_conflict 零生产调用, 冲突表恒空, 人工裁决界面无数据可裁。"""
    resolver = _resolver(tmp_path)
    await _bind_verified(resolver, "person_a", "qq", "10001", "小明")

    await resolver.resolve("telegram", "attacker-1", "小明")
    conflicts = await asyncio_to_thread(resolver.list_conflicts)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["platform"] == "telegram"
    assert conflict["platform_user_id"] == "attacker-1"
    assert conflict["display_name"] == "小明"
    # 最高置信度 = 封顶值 (0.5 < 0.7 阈值 → 必入队列)。
    assert conflict["highest_confidence"] == NICKNAME_MATCH_CONFIDENCE_CAP
    assert conflict["highest_confidence"] < CONFLICT_THRESHOLD
    assert "person_a" in conflict["candidates"]


@pytest.mark.asyncio
async def test_conflict_dedupe_same_trigger(tmp_path: Path) -> None:
    """同触发身份的未裁决冲突只留一条 (每条消息都过 resolve, 不去重会刷爆)。"""
    resolver = _resolver(tmp_path)
    await _bind_verified(resolver, "person_a", "qq", "10001", "小明")

    await resolver.resolve("telegram", "attacker-1", "小明")
    await resolver.resolve("telegram", "attacker-1", "小明")
    await resolver.resolve("telegram", "attacker-1", "小明")
    assert len(await asyncio_to_thread(resolver.list_conflicts)) == 1

    # 不同触发身份 (另一个攻击者) 各自留痕。
    await resolver.resolve("telegram", "attacker-2", "小明")
    assert len(await asyncio_to_thread(resolver.list_conflicts)) == 2


@pytest.mark.asyncio
async def test_p1_2_arbitration_decision_writes_back_verified(tmp_path: Path) -> None:
    """裁决回写闭环: 冲突 → 人工选 person_a → (telegram, attacker-1) 以 verified
    绑定落 person_identities → 后续 resolve 第一步 verified 命中返回 person_a
    (此前裁决只改 conflicts 行, 归一行为不变)。"""
    resolver = _resolver(tmp_path)
    await _bind_verified(resolver, "person_a", "qq", "10001", "小明")

    assert await resolver.resolve("telegram", "attacker-1", "小明") is None
    conflicts = await asyncio_to_thread(resolver.list_conflicts)
    assert len(conflicts) == 1

    # 人工裁决: 这个 telegram 账号确实是 person_a。
    assert await resolver.resolve_conflict(conflicts[0]["conflict_id"], "person_a") is True

    # 回写生效: 下次 resolve 直接 verified 命中 (不再进启发式/冲突路径)。
    assert await resolver.resolve("telegram", "attacker-1", "小明") == "person_a"
    # 冲突队列已清 (resolved)。
    assert await asyncio_to_thread(resolver.list_conflicts) == []

    # 裁决幂等: 已 resolved 的冲突再次裁决返回 True。
    assert await resolver.resolve_conflict(conflicts[0]["conflict_id"], "person_a") is True


@pytest.mark.asyncio
async def test_verified_direct_hit_unaffected(tmp_path: Path) -> None:
    """既有 verified 命中路径零行为变化 (不进启发式, 不产生冲突)。"""
    resolver = _resolver(tmp_path)
    await _bind_verified(resolver, "person_a", "qq", "10001", "小明")
    assert await resolver.resolve("qq", "10001", "随便什么昵称") == "person_a"
    assert await asyncio_to_thread(resolver.list_conflicts) == []


def test_arbitrate_high_confidence_no_conflict_record(tmp_path: Path) -> None:
    """高置信度候选 (>= 0.7) 不写冲突 (自动合并分支留给未来强证据信号);
    昵称路径因封顶恒不可达, 但仲裁入口本身的阈值语义不变。"""
    import json

    resolver = _resolver(tmp_path, heuristic=False)
    candidates = [
        PersonIdentity(person_id="p_hi", confidence=0.95, verified=True),
        PersonIdentity(person_id="p_lo", confidence=0.3),
    ]
    winner = resolver.arbitrate_conflict(candidates)
    assert winner is not None and winner.person_id == "p_hi"
    assert resolver.list_conflicts() == []

    # 低置信度 → 写冲突 (旧签名无 trigger, 坐标列为 None)。
    low = [PersonIdentity(person_id="p_x", confidence=0.4)]
    winner2 = resolver.arbitrate_conflict(low)
    assert winner2 is not None and winner2.person_id == "p_x"
    conflicts = resolver.list_conflicts()
    assert len(conflicts) == 1
    payload = json.loads(conflicts[0]["candidates"])
    assert payload[0]["person_id"] == "p_x"


async def asyncio_to_thread(fn, *args):  # noqa: ANN001, ANN202 — 测试便捷包装
    import asyncio

    return await asyncio.to_thread(fn, *args)
