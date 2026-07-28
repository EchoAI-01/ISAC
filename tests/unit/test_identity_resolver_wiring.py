"""身份归一主链路接线锚点单测 (S4, TODO(P4))。

验证 _resolve_identity 锚点 (由 process_message 调用): identity_resolver=None 时不
改写 profile.user_id (零行为变化); 归一命中时覆盖为 person_id (记忆按归一身份聚合);
返回 None (无归一) 保留原 master_id; resolver 抛异常降级不冒泡。以及
_build_identity_resolver 的默认关闭 / 启用构造语义。
"""

from __future__ import annotations

import pytest

from isac.channel.model import ISACMessage
from isac.gateway.identity.resolver import IdentityResolver
from isac.gateway.models import UserProfile
from isac.main import _build_identity_resolver, _resolve_identity


class _StubResolver:
    def __init__(self, person_id: str | None) -> None:
        self._person_id = person_id
        self.calls = 0

    async def resolve(self, platform: str, user_id: str, nickname: str = "") -> str | None:
        self.calls += 1
        return self._person_id


class _BoomResolver:
    async def resolve(self, platform: str, user_id: str, nickname: str = "") -> str | None:
        raise RuntimeError("resolver down")


def _msg() -> ISACMessage:
    return ISACMessage(
        msg_id="m1", platform="qq", timestamp=0, user_id="qq-123", user_name="小明", content="hi"
    )


@pytest.mark.asyncio
async def test_none_resolver_keeps_user_id() -> None:
    profile = UserProfile(user_id="master-1")
    await _resolve_identity(profile, None, _msg())
    assert profile.user_id == "master-1"  # user_mapper 原路径, 未改写


@pytest.mark.asyncio
async def test_resolver_hit_overrides_user_id() -> None:
    profile = UserProfile(user_id="master-1")
    await _resolve_identity(profile, _StubResolver("person-42"), _msg())
    assert profile.user_id == "person-42"  # 归一身份聚合


@pytest.mark.asyncio
async def test_resolver_none_result_keeps_user_id() -> None:
    profile = UserProfile(user_id="master-1")
    await _resolve_identity(profile, _StubResolver(None), _msg())
    assert profile.user_id == "master-1"


@pytest.mark.asyncio
async def test_resolver_exception_degrades_gracefully() -> None:
    profile = UserProfile(user_id="master-1")
    await _resolve_identity(profile, _BoomResolver(), _msg())  # 不冒泡
    assert profile.user_id == "master-1"


def test_build_resolver_default_off() -> None:
    assert _build_identity_resolver({}, object()) is None  # type: ignore[arg-type]
    assert _build_identity_resolver({"identity": {"enabled": False}}, object()) is None  # type: ignore[arg-type]


def test_build_resolver_enabled() -> None:
    resolver = _build_identity_resolver({"identity": {"enabled": True}}, object())  # type: ignore[arg-type]
    assert isinstance(resolver, IdentityResolver)
