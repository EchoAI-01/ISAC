"""Fix-17 会话认证端点 (CONTROL_PLANE_SPEC.md §8.2 第 5 条)。

端点:
- POST /auth/session   一次性 Bearer Token 换取 HttpOnly 会话 Cookie + CSRF Cookie
- DELETE /auth/session 登出 (清除两个 Cookie)

同源 WebUI 用这两个端点替代把裸 Bearer Token 长期存进 sessionStorage 的做法;
纯 API 客户端不受影响, 继续直接用 Authorization: Bearer 头。

不挂认证依赖 (本端点本身就是"用 Token 换 Cookie", 挂了就矛盾了); 靠请求体里的
Token 自行校验。
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, Response


def build_router(
    expected_token: str,
    tokens: Any = None,
    session_secret: bytes | None = None,
    samesite: str = "strict",
) -> Any:
    """构造 /auth/session 路由。

    expected_token: 扁平 api_token (未配置 tokens[] 时的校验依据)。
    tokens: Fix-12 解析出的 TokenScope 列表 (配置了 control.tokens[] 时非 None)。
    session_secret: 签名会话 Cookie 用的进程级密钥; None 时本端点直接 404 风格
    拒绝 (会话 Cookie 机制未启用, 不应该有调用方打这个端点)。
    samesite: FE1 会话 Cookie 的 SameSite 策略。同源 (默认) 用 "strict";
    control.cors.origins 非空 (分离 origin 跨源带 Cookie) 时由 server 传 "lax"。
    """
    from fastapi import APIRouter, HTTPException

    from isac.control.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, _find_matching_token, verify_token

    router = APIRouter(tags=["auth"])

    @router.post("/auth/session")
    async def create_session(payload: dict, request: Request, response: Response) -> dict:
        if session_secret is None:
            raise HTTPException(
                status_code=404, detail={"code": "SESSION_AUTH_DISABLED", "message": "会话 Cookie 机制未启用"}
            )
        candidate = str(payload.get("token", "") or "")
        authenticated = False
        if tokens:
            authenticated = _find_matching_token(tokens, candidate) is not None
        elif expected_token:
            authenticated = verify_token(candidate, expected_token)
        if not authenticated:
            raise HTTPException(
                status_code=401,
                detail={"code": "UNAUTHORIZED", "message": "无效或缺失 Bearer Token"},
            )
        _set_session_cookies(response, request, candidate, session_secret, samesite)
        return {"status": "ok"}

    @router.delete("/auth/session")
    async def delete_session(response: Response) -> dict:
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        response.delete_cookie(CSRF_COOKIE_NAME, path="/")
        return {"status": "ok"}

    return router


def _set_session_cookies(
    response: Any, request: Any, token: str, session_secret: bytes, samesite: str = "strict"
) -> None:
    """设置会话 Cookie (HttpOnly) + CSRF Cookie (非 HttpOnly, 前端要读它回填请求头)。

    CONTROL_PLANE_SPEC.md §8.2 第 5 条: "生产 HTTPS 环境必须同时设置 Secure,
    本机 HTTP 开发模式不得误设导致无法登录"。按当前请求的 scheme 动态判断,
    不引入新的必需配置项 (反向代理场景若终结 TLS 后以 HTTP 转发给本进程,
    应在代理层设置 X-Forwarded-Proto 并由部署方自行决定是否需要额外配置,
    此处不臆造尚不存在的信任链)。

    samesite: FE1 同源用 "strict"; 分离 origin (cors.origins 非空) 用 "lax"
    让跨源请求可带 Cookie (写操作另由 Bearer Token + CSRF 双提交兜底)。
    """
    from isac.control.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, generate_csrf_token, sign_session_cookie

    is_https = request.url.scheme == "https"
    session_value = sign_session_cookie(token, session_secret)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_value,
        httponly=True,
        samesite=samesite,
        secure=is_https,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        generate_csrf_token(),
        httponly=False,
        samesite=samesite,
        secure=is_https,
        path="/",
    )
