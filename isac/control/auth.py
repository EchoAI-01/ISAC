"""控制面认证 (DEVELOP.md 7.4)。

所有控制面请求必须携带 api_token (Bearer 认证)。
恒定时间比较 (hmac.compare_digest) 防时序攻击。

Fix-12: CONTROL_PLANE_SPEC.md §6.1 描述的 Token Scope 模型 (``control.tokens``
配置多个 {token, scopes} 条目, 按 scope 收窄权限)。未配置 ``tokens`` 时
``parse_token_scopes`` 返回 None, 调用方回退到现有单一 ``api_token`` 扁平认证
(不区分 scope, 与配置本模型之前完全一致, 向后兼容)。

Fix-17: CONTROL_PLANE_SPEC.md §8.2 第 5 条描述的会话 Cookie + CSRF 双提交模型。
同源 WebUI 通过 ``POST /auth/session`` (见 routes_auth.py) 用一次性 Bearer Token
换取签名会话 Cookie, 之后写请求带 Cookie + 匹配的 X-CSRF-Token 头即可, 不需要
把裸 Bearer Token 存进浏览器 sessionStorage。设计要点:
- 会话 Cookie 值是 "被验证过的 token 本身" 的签名打包 (base64(token) + 签名),
  不引入独立的服务端会话存储表; 签名密钥是进程级随机数 (generate_session_secret),
  重启后失效 (强制重新登录, 不是安全问题, 与"无持久化会话状态"的设计一致)。
- 签名只证明 Cookie 是本进程 /auth/session 签发的, 不构成完整的权限校验:
  make_auth_dependency/make_token_only_dependency 恢复出 token 后仍必须重新过
  一遍 verify_token/_find_matching_token (管理员轮换/吊销 Token 后, 旧 Cookie
  即使签名合法也会在这一步被拒绝)。
- CSRF 只在"本次请求是靠 Cookie 通过认证"时才校验 (纯 Bearer Header 认证的 API
  客户端不受影响, 符合 spec "纯 API 客户端继续使用 Bearer Token" 的要求); GET/
  HEAD/OPTIONS 等安全方法不校验 CSRF。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets as _secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


def verify_token(token: str | None, expected: str) -> bool:
    """校验 Bearer Token, 恒定时间比较。

    CR3-L6: hmac.compare_digest 对含非 ASCII 字符的 str 会抛 TypeError; 此前该
    异常会冒泡成 500。这里兜底为 False (失败关闭), 让调用方返回干净的 401。
    """
    if not token or not expected:
        return False
    try:
        return hmac.compare_digest(token, expected)
    except TypeError:
        return False


def token_fingerprint(token: str | None) -> str:
    """把 Bearer Token 变成不可逆的短指纹 (审计归因用, CR3-L5)。

    审计日志需要回答"谁做的", 但绝不能落裸 Token; 取 SHA-256 前 12 个十六进制
    字符足够在少量 Token 间区分, 又无法反推原值。空 Token 返回空串。
    """
    if not token:
        return ""
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"tok-{digest[:12]}"


def extract_bearer(authorization: str | None) -> str | None:
    """从 Authorization 头提取 Bearer token。"""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token or None


# Fix-17: 会话 Cookie / CSRF Cookie 的名称与请求头名称, routes_auth.py 和
# CSRFProtectionMiddleware 共用, 避免两处硬编码字符串漂移。
SESSION_COOKIE_NAME = "isac_session"
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


def generate_session_secret() -> bytes:
    """生成一个进程级随机密钥, 用于签名会话 Cookie。

    不做持久化: 进程重启后旧签名全部失效, 相当于强制所有会话重新登录, 这是
    "不引入独立会话存储表" 设计的自然代价, 不是缺陷 (纯 Bearer Header 认证的
    API 客户端完全不受影响)。
    """
    return _secrets.token_bytes(32)


def generate_csrf_token() -> str:
    """生成一个随机 CSRF Token (每次 /auth/session 登录都换新, 不复用)。"""
    return _secrets.token_urlsafe(32)


def sign_session_cookie(token: str, secret: bytes) -> str:
    """把已校验过的 token 用 AES-GCM 加密打包成会话 Cookie 值。

    R5: 原实现 ``base64url(token).hmac_hex`` 中 token 仅 base64 编码
    (可逆), 窃 Cookie 即可拿到原始 token 获得长期访问。改为 AES-GCM
    加密: nonce (12B) + ciphertext + tag (16B) 全部 base64url 编码,
    窃 Cookie 也无法还原 token (除非也拿到 secret)。

    secret 仍是进程级随机 32 字节 (generate_session_secret), 进程重启
    后旧 Cookie 全部失效 (强制重新登录, 与原行为一致)。
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    # AESGCM 要求 16/24/32 字节 key; secret 来自 generate_session_secret
    # 已是 32 字节, 直接用 (若调用方传入短 key 则用 SHA-256 派生)
    key = secret if len(secret) == 32 else hashlib.sha256(secret).digest()
    nonce = _secrets.token_bytes(12)  # GCM 推荐 12 字节 nonce
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, token.encode("utf-8"), associated_data=None)
    # 拼接 nonce + ciphertext (含 tag), base64url 编码为 Cookie 安全格式
    blob = nonce + ciphertext
    return base64.urlsafe_b64encode(blob).decode("ascii").rstrip("=")


def verify_session_cookie(cookie_value: str | None, secret: bytes) -> str | None:
    """校验并解密会话 Cookie, 解出打包的 token; 解密失败/格式错误返回 None。

    R5: AES-GCM 解密 + tag 校验 (隐式 HMAC, 无需单独 hmac.compare_digest)。
    解密成功证明 Cookie 是本进程 /auth/session 签发的, 且未被篡改; 调用方
    仍必须对解出的 token 重新跑一遍 verify_token/_find_matching_token。
    """
    if not cookie_value:
        return None
    try:
        padded = cookie_value + "=" * (-len(cookie_value) % 4)
        blob = base64.urlsafe_b64decode(padded)
    except (ValueError, UnicodeDecodeError):
        return None
    # 至少 12B nonce + 16B tag = 28B 才可能是合法 AES-GCM 输出
    if len(blob) < 28:
        return None
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = secret if len(secret) == 32 else hashlib.sha256(secret).digest()
    nonce = blob[:12]
    ciphertext = blob[12:]
    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        return plaintext.decode("utf-8")
    except (InvalidTag, ValueError, UnicodeDecodeError):
        return None


def _resolve_token(
    authorization: str | None, session_cookie: str | None, session_secret: bytes | None
) -> str | None:
    """统一解析出候选 token: 优先 Authorization Header, 缺失时回退会话 Cookie。

    session_secret 为 None (未启用会话 Cookie 机制, 如开发模式或调用方未升级)
    时不看 Cookie, 行为与引入 Fix-17 之前完全一致。
    """
    token = extract_bearer(authorization)
    if token is not None:
        return token
    if session_secret is None:
        return None
    return verify_session_cookie(session_cookie, session_secret)


def make_auth_dependency(
    expected_token: str, session_secret: bytes | None = None, setup_manager: Any = None
):
    """构造 FastAPI Bearer 认证依赖。

    返回可被 Depends() 使用的函数; 认证失败抛 HTTPException(401)。
    expected_token 为空时跳过认证 (开发模式, 不推荐生产使用)。
    session_secret 非 None 时, Authorization Header 缺失时回退校验签名会话
    Cookie (Fix-17), 使同源 WebUI 可以只靠 Cookie 完成认证。
    setup_manager 非 None 时 (T3-backend): 候选 token 也比对首登密码 hash; 且当
    "未配置 api_token + setup 未设密码"时返回 428 SETUP_REQUIRED (首登强制设
    密码, 对标 AstrBot password_change_required)。setup_manager=None 时行为与
    引入 T3 前完全一致 (向后兼容旧测试)。
    """
    from fastapi import Cookie, Header, HTTPException

    def _verify(
        authorization: str | None = Header(default=None),
        session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ) -> str:
        token = _resolve_token(authorization, session_cookie, session_secret)
        if expected_token and verify_token(token, expected_token):
            return "authenticated"
        if setup_manager is not None:
            # T3-backend: setup_manager 注入后, 认证只认 api_token 或 setup 密码;
            # setup 完成且 token 无效 → 401 (不再回退开发模式 anonymous)。
            if setup_manager.is_password_valid(token):
                return "authenticated"
            if setup_manager.is_setup_required:
                raise HTTPException(
                    status_code=428,
                    detail={"code": "SETUP_REQUIRED", "message": "首登未设置密码, 请 POST /api/v1/setup"},
                )
            raise HTTPException(
                status_code=401,
                detail={"code": "UNAUTHORIZED", "message": "无效或缺失 Bearer Token"},
            )
        if not expected_token:
            return "anonymous"  # 未配置 token 且无 setup_manager, 开发模式
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "无效或缺失 Bearer Token"},
        )

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


def make_token_only_dependency(
    tokens: list[TokenScope], session_secret: bytes | None = None, setup_manager: Any = None
):
    """构造一个只校验 Bearer Token 在 tokens[] 中存在、不检查具体 scope 的依赖。

    用于路由级别的基线认证 (等价于 make_auth_dependency, 但按 tokens[] 而不是
    单一 api_token 解析) —— scope 模型生效时, 路由级依赖也必须改用这个函数,
    否则任何不等于旧扁平 api_token 的合法 scoped token 会在到达端点级
    scope_dependency 检查之前就被路由级的旧 make_auth_dependency 拒绝 (401)。
    session_secret 非 None 时同样支持 Fix-17 的会话 Cookie 回退。
    setup_manager 非 None 时 (T3-backend): 候选 token 也比对首登密码 hash; 且
    当 setup 未设密码时返回 428 SETUP_REQUIRED (首登强制设密码)。
    """
    from fastapi import Cookie, Header, HTTPException

    def _verify(
        authorization: str | None = Header(default=None),
        session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ) -> str:
        token = _resolve_token(authorization, session_cookie, session_secret)
        matched = _find_matching_token(tokens, token)
        if matched is not None:
            return matched.token
        if setup_manager is not None:
            if setup_manager.is_password_valid(token):
                return "authenticated"
            if setup_manager.is_setup_required:
                raise HTTPException(
                    status_code=428,
                    detail={"code": "SETUP_REQUIRED", "message": "首登未设置密码, 请 POST /api/v1/setup"},
                )
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "无效或缺失 Bearer Token"},
        )

    return _verify


def make_scope_dependency_factory(
    tokens: list[TokenScope],
    session_secret: bytes | None = None,
) -> Callable[[str], Callable[..., str]]:
    """按已解析的 tokens[] 构造一个 "给定 required_scope 返回 FastAPI 依赖" 的工厂。

    每次请求: 提取 Bearer token (缺失时按 Fix-17 回退会话 Cookie), 逐条用恒定
    时间比较找匹配的 TokenScope (找不到 → 401); 匹配项的 scopes 不包含
    required_scope 也不包含 "*" (全权限通配) 时 → 403 SCOPE_FORBIDDEN。
    """
    from fastapi import Cookie, Header, HTTPException

    def factory(required_scope: str) -> Callable[..., str]:
        def _check(
            authorization: str | None = Header(default=None),
            session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        ) -> str:
            token = _resolve_token(authorization, session_cookie, session_secret)
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


class CSRFProtectionMiddleware:
    """Fix-17 CSRF 双提交校验 (CONTROL_PLANE_SPEC.md §8.2 第 5 条)。

    只对"靠会话 Cookie 完成认证"的写请求生效:
    - Authorization: Bearer ... 头存在时直接放行 (纯 API 客户端不受影响)。
    - 没有会话 Cookie 时也放行 (不是本机制要保护的路径, 下游 auth_dependency
      按自己的规则决定要不要 401)。
    - 会话 Cookie 存在且没有 Bearer 头时, 要求请求头 X-CSRF-Token 与
      csrf_token Cookie 恒定时间比较一致, 否则 403 CSRF_REQUIRED。
    GET/HEAD/OPTIONS 等安全方法不做任何校验。DELETE /auth/session (登出) 单独
    豁免: 强制登出没有可利用的安全后果 (最坏情况是用户被动退出、需要重新登录),
    卡在 CSRF 校验之前反而会让用户拿着已经生效的会话却登出不掉。

    纯 ASGI 中间件 (不用 BaseHTTPMiddleware): 只读 scope["headers"] 构造的
    Request.headers/.cookies (不触发 receive()), 不会干扰下游读取请求体。
    """

    _SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
    _CSRF_EXEMPT_PATHS = frozenset({"/api/v1/auth/session"})

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] in self._SAFE_METHODS
            or (scope["method"] == "DELETE" and scope["path"] in self._CSRF_EXEMPT_PATHS)
        ):
            await self.app(scope, receive, send)
            return

        from starlette.requests import Request

        request = Request(scope, receive=receive)
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            await self.app(scope, receive, send)
            return

        if request.cookies.get(SESSION_COOKIE_NAME) is None:
            await self.app(scope, receive, send)
            return

        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        csrf_header = request.headers.get(CSRF_HEADER_NAME)
        if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
            from starlette.responses import JSONResponse

            response = JSONResponse(
                {"detail": {"code": "CSRF_REQUIRED", "message": "缺少或不匹配的 X-CSRF-Token"}},
                status_code=403,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
