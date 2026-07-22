"""控制面认证 (DEVELOP.md 7.4)。

所有控制面请求必须携带 api_token (Bearer 认证)。
恒定时间比较 (hmac.compare_digest) 防时序攻击。
"""

from __future__ import annotations

import hmac


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
