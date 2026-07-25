"""控制面认证 (DEVELOP.md 7.4)。

所有控制面请求必须携带 api_token (Bearer 认证)。
恒定时间比较 (hmac.compare_digest) 防时序攻击。

Fix-12: CONTROL_PLANE_SPEC.md §6.1 描述的 Token Scope 模型 (``control.tokens``
配置多个 {token, scopes} 条目, 按 scope 收窄权限)。未配置 ``tokens`` 时
``parse_token_scopes`` 返回 None, 调用方回退到现有单一 ``api_token`` 扁平认证
(不区分 scope, 与配置本模型之前完全一致, 向后兼容)。
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


def verify_token(token: str | None, expected: str) -> bool:
    """校验 Bearer Token, 恒定时间比较。"""
    if not token or not expected:
        return False
    return hmac.compare_digest(token, expected)


def extract_bearer(authorization: str | None) -> str | None:
    """从 Authorization 头提取 Bearer token。"""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token or None


def make_auth_dependency(expected_token: str):
    """构造 FastAPI Bearer 认证依赖。

    返回可被 Depends() 使用的函数; 认证失败抛 HTTPException(401)。
    expected_token 为空时跳过认证 (开发模式, 不推荐生产使用)。
    """
    from fastapi import Header, HTTPException

    def _verify(authorization: str | None = Header(default=None)) -> str:
        if not expected_token:
            return "anonymous"  # 未配置 token, 开发模式
        token = extract_bearer(authorization)
        if not verify_token(token, expected_token):
            raise HTTPException(
                status_code=401,
                detail={"code": "UNAUTHORIZED", "message": "无效或缺失 Bearer Token"},
            )
        return "authenticated"

    return _verify


@dataclass(frozen=True)
class TokenScope:
    """一个 Token 及其被授予的 scope 集合 (CONTROL_PLANE_SPEC.md §6.1)。"""

    token: str
    scopes: frozenset[str]


def parse_token_scopes(config: dict[str, Any]) -> list[TokenScope] | None:
    """从控制面配置解析 ``tokens: [{token, scopes}, ...]``。

    未配置 (或配置为空/全部缺 token 字段) 时返回 None, 表示继续使用现有单一
    ``api_token`` 扁平认证, 不引入 scope 校验 (向后兼容默认行为不变)。
    """
    raw_tokens = config.get("tokens")
    if not raw_tokens:
        return None
    parsed: list[TokenScope] = []
    for entry in raw_tokens:
        token = str((entry or {}).get("token") or "")
        if not token:
            continue
        scopes = frozenset(str(s) for s in (entry.get("scopes") or []))
        parsed.append(TokenScope(token=token, scopes=scopes))
    return parsed or None


def _find_matching_token(tokens: list[TokenScope], token: str | None) -> TokenScope | None:
    """逐条用恒定时间比较找匹配的 TokenScope; 找不到返回 None。"""
    for entry in tokens:
        if verify_token(token, entry.token):
            return entry
    return None


def make_token_only_dependency(tokens: list[TokenScope]):
    """构造一个只校验 Bearer Token 在 tokens[] 中存在、不检查具体 scope 的依赖。

    用于路由级别的基线认证 (等价于 make_auth_dependency, 但按 tokens[] 而不是
    单一 api_token 解析) —— scope 模型生效时, 路由级依赖也必须改用这个函数,
    否则任何不等于旧扁平 api_token 的合法 scoped token 会在到达端点级
    scope_dependency 检查之前就被路由级的旧 make_auth_dependency 拒绝 (401)。
    """
    from fastapi import Header, HTTPException

    def _verify(authorization: str | None = Header(default=None)) -> str:
        token = extract_bearer(authorization)
        matched = _find_matching_token(tokens, token)
        if matched is None:
            raise HTTPException(
                status_code=401,
                detail={"code": "UNAUTHORIZED", "message": "无效或缺失 Bearer Token"},
            )
        return matched.token

    return _verify


def make_scope_dependency_factory(
    tokens: list[TokenScope],
) -> Callable[[str], Callable[..., str]]:
    """按已解析的 tokens[] 构造一个 "给定 required_scope 返回 FastAPI 依赖" 的工厂。

    每次请求: 提取 Bearer token, 逐条用恒定时间比较找匹配的 TokenScope (找不到
    → 401); 匹配项的 scopes 不包含 required_scope 也不包含 "*" (全权限通配) 时
    → 403 SCOPE_FORBIDDEN。
    """
    from fastapi import Header, HTTPException

    def factory(required_scope: str) -> Callable[..., str]:
        def _check(authorization: str | None = Header(default=None)) -> str:
            token = extract_bearer(authorization)
            matched = _find_matching_token(tokens, token)
            if matched is None:
                raise HTTPException(
                    status_code=401,
                    detail={"code": "UNAUTHORIZED", "message": "无效或缺失 Bearer Token"},
                )
            if required_scope not in matched.scopes and "*" not in matched.scopes:
                raise HTTPException(
                    status_code=403,
                    detail={"code": "SCOPE_FORBIDDEN", "message": f"缺少 scope: {required_scope}"},
                )
            return matched.token

        return _check

    return factory
