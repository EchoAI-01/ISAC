"""控制面认证 (DEVELOP.md 7.4)。

所有控制面请求必须携带 api_token (Bearer 认证)。
"""

from __future__ import annotations


def verify_token(token: str | None, expected: str) -> bool:
    """校验 Bearer Token。

    TODO(Day 71): 恒定时间比较 (hmac.compare_digest) 防时序攻击。
    """
    if not token or not expected:
        return False
    return token == expected


def extract_bearer(authorization: str | None) -> str | None:
    """从 Authorization 头提取 Bearer token。"""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token or None
