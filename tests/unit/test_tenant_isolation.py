"""O1 多租户/组织隔离业务测试。

覆盖:
- TenantIsolationGuard.namespace_for: enabled 时加租户前缀; disabled/默认租户直通
- TenantIsolationGuard.check_access: enabled 时跨租户拒绝; disabled 恒放行
- TenantIsolationGuard.enforce: 给 SQL 查询加 tenant_id 谓词
- TenantIsolationGuard.assert_visible: 跨租户不可见抛 PermissionError
- 默认单租户 passthrough 零行为变化
"""

from __future__ import annotations

import sqlite3

import pytest

from isac.runtime.tenancy.isolation import TenantIsolationGuard
from isac.runtime.tenancy.models import DEFAULT_ORG, DEFAULT_TENANT, TenantContext


def _tenant(org: str = "acme", tenant: str = "t1") -> TenantContext:
    return TenantContext(organization_id=org, tenant_id=tenant)


# ── namespace_for ───────────────────────────────────────────────


def test_namespace_for_disabled_returns_base_unchanged() -> None:
    """disabled 时命名空间原样返回 (零行为变化)."""
    guard = TenantIsolationGuard(enabled=False)
    assert guard.namespace_for("a1:memory", _tenant("acme", "t1")) == "a1:memory"


def test_namespace_for_default_tenant_returns_base_unchanged() -> None:
    """enabled 但默认租户时仍直通 (避免单租户场景污染)."""
    guard = TenantIsolationGuard(enabled=True)
    default_tenant = TenantContext()  # 默认 default/default
    assert guard.namespace_for("a1:memory", default_tenant) == "a1:memory"


def test_namespace_for_enabled_non_default_adds_prefix() -> None:
    """enabled + 非默认租户时加 org:tenant:base 前缀."""
    guard = TenantIsolationGuard(enabled=True)
    result = guard.namespace_for("a1:memory", _tenant("acme", "t1"))
    assert result == "acme:t1:a1:memory"


# ── check_access ────────────────────────────────────────────────


def test_check_access_disabled_always_allows() -> None:
    guard = TenantIsolationGuard(enabled=False)
    # 任何 resource_org 都放行 (零行为变化)
    assert guard.check_access("acme", _tenant("other", "t1")) is True
    assert guard.check_access("default", _tenant("acme", "t1")) is True


def test_check_access_enabled_same_org_allows() -> None:
    guard = TenantIsolationGuard(enabled=True)
    assert guard.check_access("acme", _tenant("acme", "t1")) is True


def test_check_access_enabled_different_org_rejects() -> None:
    """跨租户不可见 (resource_org != tenant.org 且 != DEFAULT)."""
    guard = TenantIsolationGuard(enabled=True)
    assert guard.check_access("acme", _tenant("other", "t1")) is False


def test_check_access_enabled_default_org_allows_anyone() -> None:
    """默认 org 资源对所有租户可见 (全局共享)."""
    guard = TenantIsolationGuard(enabled=True)
    assert guard.check_access(DEFAULT_ORG, _tenant("acme", "t1")) is True


# ── enforce SQL 谓词注入 ────────────────────────────────────────


def test_enforce_disabled_returns_original_query() -> None:
    """disabled 时 SQL 查询不变 (零行为变化)."""
    guard = TenantIsolationGuard(enabled=False)
    query = "SELECT * FROM episodes WHERE agent_id = ?"
    params = ["a1"]
    new_query, new_params = guard.enforce(query, params, _tenant("acme", "t1"))
    assert new_query == query
    assert new_params == params


def test_enforce_default_tenant_returns_original_query() -> None:
    """enabled 但默认租户时不变 (单租户场景)."""
    guard = TenantIsolationGuard(enabled=True)
    query = "SELECT * FROM episodes WHERE agent_id = ?"
    params = ["a1"]
    new_query, new_params = guard.enforce(query, params, TenantContext())
    assert new_query == query
    assert new_params == params


def test_enforce_enabled_adds_tenant_id_predicate() -> None:
    """enabled + 非默认租户时给查询加 tenant_id 谓词."""
    guard = TenantIsolationGuard(enabled=True)
    query = "SELECT * FROM episodes WHERE agent_id = ?"
    params = ["a1"]
    new_query, new_params = guard.enforce(query, params, _tenant("acme", "t1"))
    # 新查询含 tenant_id 谓词
    assert "tenant_id = ?" in new_query
    assert "acme" in new_params
    assert "t1" in new_params
    assert "a1" in new_params


def test_enforce_query_without_where_adds_where_tenant() -> None:
    """无 WHERE 的查询也能注入 (追加 WHERE tenant_id)."""
    guard = TenantIsolationGuard(enabled=True)
    query = "SELECT * FROM episodes"
    params: list[str] = []
    new_query, new_params = guard.enforce(query, params, _tenant("acme", "t1"))
    assert "WHERE" in new_query.upper()
    assert "tenant_id = ?" in new_query
    assert "acme" in new_params


# ── enforce: 真实 sqlite3 执行验证 (CR2-Fix-18 子查询包裹) ─────────


def _make_scoped_db() -> sqlite3.Connection:
    """构造一个含 organization_id/tenant_id/is_shared 列的最小测试表。"""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE episodes (id TEXT, agent_id TEXT, organization_id TEXT, "
        "tenant_id TEXT, is_shared INTEGER)"
    )
    conn.executemany(
        "INSERT INTO episodes VALUES (?, ?, ?, ?, ?)",
        [
            ("e1", "a1", "acme", "t1", 0),  # acme/t1 自己的私有记忆
            ("e2", "a2", "other", "t2", 1),  # 另一租户标记为"共享"的记忆
            ("e3", "a3", "other", "t2", 0),  # 另一租户的私有记忆 (不共享)
        ],
    )
    conn.commit()
    return conn


def test_enforce_blocks_top_level_or_bypass() -> None:
    """CR2-Fix-18: 含顶层 OR 的查询此前会被操作符优先级绕过 —— 拼接后
    `WHERE org=? AND tenant=? AND agent_id=? OR is_shared=1` 里 AND 优先级
    高于 OR, 导致其他租户 is_shared=1 的行也被返回。用真实 sqlite3 验证
    子查询包裹修复后不再泄露。

    注意: 子查询包裹要求内层查询投影出 organization_id/tenant_id 列供外层
    WHERE 引用, 故用 SELECT * (与本项目 metadata.py 里的实际查询写法一致)。
    """
    conn = _make_scoped_db()
    guard = TenantIsolationGuard(enabled=True)
    query = "SELECT * FROM episodes WHERE agent_id = ? OR is_shared = 1"
    params = ["a1"]
    new_query, new_params = guard.enforce(query, params, _tenant("acme", "t1"))
    rows = conn.execute(new_query, new_params).fetchall()
    ids = {r[0] for r in rows}
    assert ids == {"e1"}  # 只有 acme/t1 自己的记忆; other/t2 的 e2 (is_shared=1) 不泄露
    conn.close()


def test_enforce_preserves_order_by_and_limit() -> None:
    """CR2-Fix-18: 子查询包裹后, 原查询自带的 ORDER BY/LIMIT 仍正常生效。"""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE episodes (id TEXT, organization_id TEXT, tenant_id TEXT, created_at INTEGER)")
    conn.executemany(
        "INSERT INTO episodes VALUES (?, ?, ?, ?)",
        [
            ("e1", "acme", "t1", 100),
            ("e2", "acme", "t1", 300),
            ("e3", "acme", "t1", 200),
            ("e4", "other", "t2", 50),  # 排序最靠后, 无论过滤先后都会被 LIMIT 排除
        ],
    )
    conn.commit()
    guard = TenantIsolationGuard(enabled=True)
    query = "SELECT * FROM episodes ORDER BY created_at DESC LIMIT 2"
    new_query, new_params = guard.enforce(query, [], _tenant("acme", "t1"))
    rows = conn.execute(new_query, new_params).fetchall()
    assert [r[0] for r in rows] == ["e2", "e3"]
    conn.close()


def test_enforce_query_without_where_filters_correctly() -> None:
    """CR2-Fix-18: 无 WHERE 的查询包裹后, 确实按租户过滤了实际返回的行
    (不只是字符串层面出现了 WHERE)。"""
    conn = _make_scoped_db()
    guard = TenantIsolationGuard(enabled=True)
    query = "SELECT * FROM episodes"
    new_query, new_params = guard.enforce(query, [], _tenant("acme", "t1"))
    rows = conn.execute(new_query, new_params).fetchall()
    assert {r[0] for r in rows} == {"e1"}
    conn.close()


# ── assert_visible ──────────────────────────────────────────────


def test_assert_visible_disabled_does_not_raise() -> None:
    guard = TenantIsolationGuard(enabled=False)
    # 任何租户资源都可见 (不抛)
    guard.assert_visible("acme", _tenant("other", "t1"))


def test_assert_visible_enabled_same_org_does_not_raise() -> None:
    guard = TenantIsolationGuard(enabled=True)
    guard.assert_visible("acme", _tenant("acme", "t1"))


def test_assert_visible_enabled_different_org_raises_permission_error() -> None:
    """跨租户不可见时抛 PermissionError."""
    guard = TenantIsolationGuard(enabled=True)
    with pytest.raises(PermissionError):
        guard.assert_visible("acme", _tenant("other", "t1"))


# ── 默认单租户 passthrough ───────────────────────────────────────


def test_default_tenant_is_default_property() -> None:
    default = TenantContext()
    assert default.is_default is True
    assert default.organization_id == DEFAULT_ORG
    assert default.tenant_id == DEFAULT_TENANT


def test_non_default_tenant_is_default_false() -> None:
    non_default = _tenant("acme", "t1")
    assert non_default.is_default is False
