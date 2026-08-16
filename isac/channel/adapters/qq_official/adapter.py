"""QQ 官方机器人平台适配器 (O4, DEVELOP.md 3.3)。

S7 激活: QQ 官方机器人开放平台 Webhook 回调 + 出站消息发送。不引入 botpy SDK,
用项目既有依赖 httpx (HTTP) + uvicorn (服务端) + cryptography (Ed25519) 实现。

入站 (``start`` 起一个内部 uvicorn Server + FastAPI app):
- 回调地址验证握手 (op=13): 请求体 ``{"op":13,"d":{"plain_token":..., "event_ts":...}}``;
  用 Ed25519 私钥对 ``event_ts + plain_token`` 签名, 响应
  ``{"plain_token":..., "signature": <hex128>}``。
- 常规事件验签: 请求头 ``X-Signature-Ed25519`` (hex sig) + ``X-Signature-Timestamp``;
  msg = ``timestamp + raw_body``, 公钥验签 (失败 401)。
- 事件: op=0 含 t=事件名; AT_MESSAGE_CREATE (频道 @ 消息, data.channel_id) /
  C2C_MESSAGE_CREATE (私聊, data.author.user_openid) /
  GROUP_AT_MESSAGE_CREATE (群 @ 消息, data.group_openid); 取 author.member_openid /
  user_openid / author.group_member_openid 作 user_id, msg data.id 作 msg_id (供被动回复)。
- 验签字节序核对自 bot.q.qq.com 官方文档: seed = bot_secret 重复双倍直到 >=32 字节,
  取前 32 字节作 Ed25519 seed (与 Go ``strings.Repeat(seed, 2)`` 等价)。

出站 (``send``):
- access_token: POST ``https://bots.qq.com/app/getAppAccessToken`` body
  ``{"appId", "clientSecret"}`` → ``{"access_token", "expires_in"}``; 缓存 + 提前 60s。
- 频道消息: POST ``/channels/{channel_id}/messages`` Header ``Authorization: QQBot
  <token>``, body ``{"content", "msg_type":0, "msg_id"}`` (msg_id 被动回复必带)。
- 群消息: POST ``/v2/groups/{group_openid}/messages``, body 同上。
- 被动回复: msg_id 从 ``message.reply_to`` 取 (消息事件里的 data.id), None 时降级
  主动推送 (受频次限制, 日志记录)。

默认关闭: 仅当 ``channels.qq_official.enabled=true`` 时经 main._register_channel_adapters
注册; 未配置时 start/stop/send 无副作用, 零行为变化。与 OneBot 的 "qq" 并存不撞键。
回调地址端口限制为 80/443/8080/8443 (官方要求, 生产部署需注意; 测试可不绑真实端口)。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Any

import httpx

from isac.channel.base import PlatformAdapter
from isac.channel.model import ISACMessage
from isac.channel.webhook_guard import DEFAULT_MAX_WEBHOOK_BODY_BYTES, read_body_limited
from isac.utils.logger import get_logger

logger = get_logger(__name__)

# token 换取与消息发送端点 (相对 api_base 或全局)
_TOKEN_PATH = "/getAppAccessToken"  # POST https://bots.qq.com/app
_TOKEN_BASE = "https://bots.qq.com/app"
_CHANNEL_MESSAGE_PATH = "/channels/{channel_id}/messages"
_GROUP_MESSAGE_PATH = "/v2/groups/{group_openid}/messages"
# token 缓存提前刷新窗口 (秒); QQ 默认 expires_in=7200, 提前 60s 避免临界过期
_TOKEN_REFRESH_LEAD_SECONDS = 60.0
# Webhook 默认监听 host/port/path (官方限制端口 80/443/8080/8443, 默认 8443)
_DEFAULT_WEBHOOK_HOST = "127.0.0.1"  # O11: 与飞书适配器默认 127.0.0.1 一致, 避免 0.0.0.0 误暴露
_DEFAULT_WEBHOOK_PORT = 8443
_DEFAULT_WEBHOOK_PATH = "/qq_official/callback"
# Ed25519 seed 长度
_ED25519_SEED_SIZE = 32
# Fix-24: op=13 验证握手签名 oracle 限流默认值 (见 _handle_validation 说明)。
_DEFAULT_VALIDATION_RATE_LIMIT = 5
_DEFAULT_VALIDATION_RATE_WINDOW_SECONDS = 600.0


class QQOfficialAdapter(PlatformAdapter):
    """QQ 官方机器人 Webhook 适配器 (S7 激活)。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._app_id = str(config.get("app_id", "") or "")
        self._secret = str(config.get("secret", "") or "")
        self._sandbox = bool(config.get("sandbox", False))
        self._api_base = str(
            config.get("api_base", "https://sandbox.api.sgroup.qq.com" if self._sandbox else "https://api.sgroup.qq.com")
            or "https://api.sgroup.qq.com"
        )
        # webhook 服务端配置
        self._webhook_host = str(config.get("webhook_host", _DEFAULT_WEBHOOK_HOST) or _DEFAULT_WEBHOOK_HOST)
        self._webhook_port = int(config.get("webhook_port", _DEFAULT_WEBHOOK_PORT) or _DEFAULT_WEBHOOK_PORT)
        self._webhook_path = str(config.get("webhook_path", _DEFAULT_WEBHOOK_PATH) or _DEFAULT_WEBHOOK_PATH)
        # Fix-76: webhook 请求体体积上限 (验签前先限流读取, 防超大 body 打爆内存)
        self._max_body_bytes = int(config.get("max_body_bytes", DEFAULT_MAX_WEBHOOK_BODY_BYTES))
        self._running = False
        self._server: Any = None
        self._serve_task: asyncio.Task[Any] | None = None
        self._cached_token: tuple[str, float] | None = None
        # 注入式 httpx transport (供测试 mock HTTP; 生产为 None 走真实网络)
        self._http_transport: Any | None = None
        self.on_message = None  # type: ignore[assignment]  # 由 ChannelRegistry 注入
        # Fix-24: op=13 验证握手限流状态 (滑动窗口, 见 _handle_validation)。
        self._validation_rate_limit = int(
            config.get("validation_rate_limit", _DEFAULT_VALIDATION_RATE_LIMIT) or _DEFAULT_VALIDATION_RATE_LIMIT
        )
        self._validation_rate_window_seconds = float(
            config.get("validation_rate_window_seconds", _DEFAULT_VALIDATION_RATE_WINDOW_SECONDS)
            or _DEFAULT_VALIDATION_RATE_WINDOW_SECONDS
        )
        self._validation_timestamps: deque[float] = deque()

    @property
    def platform_name(self) -> str:
        return "qq_official"

    async def start(self) -> None:
        """启动 webhook 回调服务端 (FastAPI + uvicorn Server)。

        未配置 secret 时也能 start (服务可起, 但验签会全部失败)。
        """
        if self._running:
            return
        try:
            import uvicorn
            from fastapi import FastAPI
        except ImportError as exc:  # pragma: no cover - 依赖已在 pyproject.toml
            raise ImportError(
                "QQ 官方适配器需要 fastapi + uvicorn (已在项目依赖中)。若缺失请运行 uv sync --all-extras"
            ) from exc
        app = FastAPI()

        app.add_api_route(self._webhook_path, self._handle_callback, methods=["POST"])
        config = uvicorn.Config(
            app, host=self._webhook_host, port=self._webhook_port, log_level="warning",
        )
        self._server = uvicorn.Server(config)
        self._running = True
        self._serve_task = asyncio.create_task(
            self._server.serve(), name=f"qq-official-webhook-{self._webhook_port}"
        )
        logger.info(
            "QQ 官方机器人适配器 webhook 服务已启动",
            app_id=self._app_id, host=self._webhook_host, port=self._webhook_port, path=self._webhook_path,
        )

    async def stop(self) -> None:
        """关闭 webhook 服务端。"""
        self._running = False
        if self._server is not None:
            self._server.should_exit = True
        if self._serve_task is not None:
            try:
                await asyncio.wait_for(self._serve_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._serve_task.cancel()
            self._serve_task = None

    async def _handle_callback(self, request: Any) -> dict:
        """Webhook 入站主入口: 验签 → 解析事件 → on_message → 确认响应。

        op=13 (验证握手): 不验签 (是握手请求), 直接签名回 plain_token+signature。
        op=0 (dispatch event): 验签 + 解析事件类型 → 规范化 ISACMessage → on_message。
        其他 op: 直接返回 ``{"opcode": 12}`` (ACK, 与官方 SDK 行为一致)。
        """
        # 取 raw body (验签需要原始字节, 不能 json 后再序列化)
        try:
            # Fix-76: 限流读取 —— request.body() 全量读入内存且无上限, 而验签在
            # 读取之后, 超大 body (含 chunked) 在签名校验之前即可打爆内存。
            raw_body = await read_body_limited(request, self._max_body_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("QQ 官方 webhook 取 body 失败", error=str(exc))
            return {}
        if raw_body is None:
            logger.warning("QQ 官方 webhook 请求体超限, 拒绝", limit=self._max_body_bytes)
            return {}
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("QQ 官方 webhook 收到非 JSON 请求体", error=str(exc))
            return {}
        # NOTE: 用 `op_raw is None` 判定而非 `or` —— 0 在 Python 是 falsy,
        # `0 or -1` = -1 会把 op=0 (dispatch event) 误判为未知 op。
        op_raw = payload.get("op", -1)
        op = -1 if op_raw is None else int(op_raw)
        # op=13: 回调地址验证握手 (无需验签, 是握手本身)
        if op == 13:
            return self._handle_validation(payload.get("d") or {})
        # op=0 (dispatch event) 之前的 op (10=HELLO, 11=HEARTBEAT 等): 直接 ACK
        if op != 0:
            logger.debug("QQ 官方 webhook 忽略 op", op=op)
            return {"opcode": 12}
        # op=0: 常规事件, 必须验签
        if not self._verify_signature(request, raw_body):
            logger.warning("QQ 官方 webhook 验签失败, 拒绝事件")
            return {"opcode": 12, "error": "signature mismatch"}
        return await self._dispatch_event(payload)

    def _handle_validation(self, data: dict) -> dict:
        """回调地址验证握手: 用私钥对 (event_ts + plain_token) 签名, 回响应。

        Fix-24: 官方协议要求响应 ``Ed25519_sign(event_ts + plain_token)``, 与
        op=0 常规事件验签的消息格式 ``Ed25519_sign(timestamp + raw_body)`` 共享
        同一份私钥且字段拼接方式相同 —— 这个格式由官方协议规定, ISAC 不能单方面
        改签名内容 (会导致真实的官方验证握手失败)。但攻击者可以拿任意想伪造的
        事件 JSON 当 ``plain_token``、当前时间当 ``event_ts`` 请求这个"握手",
        拿到的签名对 op=0 验签而言就是一份合法签名 (把同一段 JSON 原样当 raw_body
        重放即可绕过验签)。协议格式改不了, 改用限流收紧这个签名 oracle 的开放度:
        默认滑动窗口 10 分钟最多 5 次, 超过静默拒绝 (不签名, 不告知攻击者具体
        限流细节)。真实的官方验证握手通常只在控制台保存回调地址时触发, 正常运维
        频率远低于此默认值; 需要更高频率可通过 config 的
        ``validation_rate_limit``/``validation_rate_window_seconds`` 调整。
        """
        plain_token = str(data.get("plain_token", "") or "")
        event_ts = str(data.get("event_ts", "") or "")
        if not plain_token or not event_ts:
            logger.warning("QQ 官方验证握手缺 plain_token/event_ts", data=data)
            return {}
        if not self._allow_validation_attempt():
            logger.warning(
                "QQ 官方验证握手请求过于频繁, 拒绝签名 (疑似签名 oracle 滥用)",
                limit=self._validation_rate_limit, window_seconds=self._validation_rate_window_seconds,
            )
            return {}
        try:
            signature = self._sign(f"{event_ts}{plain_token}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("QQ 官方验证握手签名失败", error=str(exc))
            return {}
        return {"plain_token": plain_token, "signature": signature}

    def _allow_validation_attempt(self) -> bool:
        """滑动窗口限流: 记录本次调用时间, 清理窗口外的旧记录, 判断是否超限。"""
        now = time.monotonic()
        window_start = now - self._validation_rate_window_seconds
        while self._validation_timestamps and self._validation_timestamps[0] < window_start:
            self._validation_timestamps.popleft()
        if len(self._validation_timestamps) >= self._validation_rate_limit:
            return False
        self._validation_timestamps.append(now)
        return True

    def _verify_signature(self, request: Any, raw_body: bytes) -> bool:
        """常规事件验签: msg = X-Signature-Timestamp + raw_body, 公钥验签。

        未配置 secret 时拒绝所有事件 (生产应配置)。
        """
        if not self._secret:
            logger.warning("QQ 官方 webhook 未配置 secret, 拒绝事件 (验签无法进行)")
            return False
        try:
            headers = request.headers
        except Exception:  # noqa: BLE001
            return False
        sig_hex = str(headers.get("X-Signature-Ed25519", "") or "")
        timestamp = str(headers.get("X-Signature-Timestamp", "") or "")
        if not sig_hex or not timestamp:
            return False
        # R2: 校验 timestamp 新鲜度, 拒绝重放攻击 (>5 分钟偏离视为重放)。
        try:
            ts_int = int(timestamp)
        except ValueError:
            logger.warning("QQ 官方 webhook timestamp 非整数, 拒绝")
            return False
        if abs(time.time() - ts_int) > 300:
            logger.warning(
                "QQ 官方 webhook timestamp 偏离本地时间 >300s, 疑似重放, 拒绝",
                offset_seconds=int(time.time() - ts_int),
            )
            return False
        try:
            import binascii


            signature = binascii.unhexlify(sig_hex)
            public_key = self._derive_public_key()
            msg = (timestamp + raw_body.decode("utf-8", errors="replace")).encode("utf-8")
            public_key.verify(signature, msg)  # 失败抛 InvalidSignature
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("QQ 官方验签异常", error=str(exc))
            return False

    def _sign(self, msg: str) -> str:
        """用派生私钥对 msg 签名, 返回 hex 编码 (128 字符)。"""
        import binascii


        private_key = self._derive_private_key()
        signature = private_key.sign(msg.encode("utf-8"))
        return binascii.hexlify(signature).decode("ascii")

    def _derive_private_key(self) -> Any:
        """从 bot_secret 派生 Ed25519 私钥 (字节序核对自 bot.q.qq.com 官方文档)。"""
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        seed = _derive_seed(self._secret)
        return Ed25519PrivateKey.from_private_bytes(seed)

    def _derive_public_key(self) -> Any:
        """公钥从私钥推导 (验签用)。"""
        return self._derive_private_key().public_key()

    async def _dispatch_event(self, payload: dict) -> dict:
        """解析 op=0 事件 → 规范化 ISACMessage → on_message。"""
        event_type = str(payload.get("t", "") or "")
        data = payload.get("d") or {}
        msg = self._build_isac_message(event_type, data)
        if msg is not None and self.on_message is not None:
            try:
                await self.on_message(msg)  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001
                logger.warning("QQ 官方 on_message 处理异常", error=str(exc))
        return {"opcode": 12}  # ACK

    def _build_isac_message(self, event_type: str, data: dict) -> ISACMessage | None:
        """从事件 data 规范化 ISACMessage。

        - AT_MESSAGE_CREATE (频道): data.channel_id (group_id), data.author.member_openid
          (user_id), data.id (msg_id 供被动回复)
        - GROUP_AT_MESSAGE_CREATE (群): data.group_openid (group_id),
          data.author.member_openid (user_id), data.id
        - C2C_MESSAGE_CREATE (私聊): data.author.user_openid (user_id), data.id
        """
        if event_type not in (
            "AT_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE",
        ):
            logger.debug("QQ 官方忽略非消息事件", event_type=event_type)
            return None
        author = data.get("author") or {}
        msg_id = str(data.get("id", "") or "")
        content = str(data.get("content", "") or "").strip()
        # @机器人会带 <@bot_appid> 前缀, 简单剥离
        content = _strip_at_prefix(content)
        if event_type == "AT_MESSAGE_CREATE":
            user_id = str(author.get("member_openid", "") or "")
            group_id = str(data.get("channel_id", "") or "")
        elif event_type == "GROUP_AT_MESSAGE_CREATE":
            user_id = str(author.get("member_openid", "") or "")
            group_id = str(data.get("group_openid", "") or "")
        else:  # C2C_MESSAGE_CREATE
            user_id = str(author.get("user_openid", "") or "")
            group_id = ""
        if not user_id:
            logger.warning("QQ 官方事件缺 author openid, 丢弃", event_type=event_type)
            return None
        return ISACMessage(
            msg_id=msg_id,
            platform="qq_official",
            timestamp=int(time.time()),
            user_id=user_id,
            user_name=user_id,  # QQ 官方不直接给昵称
            group_id=group_id or None,
            content=content,
            reply_to=msg_id or None,  # 被动回复需要 msg_id
            metadata={"qq_official_source": event_type},
        )

    async def send(self, message: ISACMessage) -> bool:
        """发送文本消息到 QQ 官方 (频道或群)。

        group_id 非空 → 频道或群 (按 group_id 前缀区分: oc_/channel_ 类前缀走频道,
        否则群); reply_to (被动回复 msg_id) 优先带, 否则降级主动推送。
        """
        if not self._app_id or not self._secret:
            logger.warning("QQ 官方 send 缺 app_id/secret, 跳过")
            return False
        target = str(message.group_id or message.user_id or "")
        if not target:
            logger.warning("QQ 官方 send 缺 target (group_id/user_id 均空)")
            return False
        token = await self._get_access_token()
        if not token:
            return False
        # 频道 channel_id 通常含数字; 群 group_openid 含字母数字。简化判定:
        # 若 group_id 非空就当作群 (因为频道是特殊场景); 真实部署可按 channel_id 规则细化
        msg_id = str(message.reply_to or "")  # 被动回复必带
        body = {
            "content": str(message.content or ""),
            "msg_type": 0,  # 0=文本
            "msg_id": msg_id or None,
            "event_id": "",  # 群消息用 event_id, 当前未支持, 留空
        }
        # 去掉 None 值 (QQ API 不接受 None 字段)
        body = {k: v for k, v in body.items() if v is not None and v != ""}
        try:
            source = str((message.metadata or {}).get("qq_official_source", "") or "")
            if source == "AT_MESSAGE_CREATE":
                # 频道端点: POST /channels/{channel_id}/messages (channel_id 在 group_id)
                url = f"{self._api_base}{_CHANNEL_MESSAGE_PATH.format(channel_id=target)}"
            elif message.group_id:
                # 群消息端点 (group_openid)
                url = f"{self._api_base}{_GROUP_MESSAGE_PATH.format(group_openid=target)}"
            else:
                # C2C 私聊端点 (user openid)
                url = f"{self._api_base}/v2/users/{target}/messages"
            resp = await self._http_post(
                url,
                json_body=body,
                headers={"Authorization": f"QQBot {token}", "Content-Type": "application/json"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("QQ 官方 send 消息发送失败", error=str(exc))
            return False
        if resp is None:
            return False
        return _send_response_ok(resp)

    async def _get_access_token(self) -> str | None:
        """获取 access_token (缓存 + 提前 60s 刷新)。"""
        if self._cached_token is not None:
            token, expires_at = self._cached_token
            if time.monotonic() < expires_at:
                return token
        body = {"appId": self._app_id, "clientSecret": self._secret}
        try:
            resp = await self._http_post(
                f"{_TOKEN_BASE}{_TOKEN_PATH}",
                json_body=body,
                headers={"Content-Type": "application/json"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("QQ 官方 access_token 换取失败", error=str(exc))
            return None
        if resp is None:
            return None
        token = str(resp.get("access_token", "") or "")
        expires_in = int(resp.get("expires_in", 7200) or 7200)
        if not token:
            return None
        self._cached_token = (token, time.monotonic() + max(60, expires_in - _TOKEN_REFRESH_LEAD_SECONDS))
        return token

    async def _http_post(self, url: str, *, json_body: dict, headers: dict) -> dict | None:
        """统一 HTTP POST (生产 httpx.AsyncClient; 测试可注入 transport mock)。"""
        transport = self._http_transport
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await client.post(url, json=json_body, headers=headers, timeout=10.0)
        if resp.status_code >= 400:
            logger.warning("QQ 官方 HTTP 非 2xx", url=url, status=resp.status_code, body=resp.text[:200])
            return None
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("QQ 官方 HTTP 响应非 JSON", url=url, error=str(exc))
            return None

    def set_http_transport(self, transport: Any) -> None:
        """供测试注入 httpx.MockTransport (生产不调用)。"""
        self._http_transport = transport


def _send_response_ok(resp: dict) -> bool:
    """Fix-56: QQ 开放平台 OpenAPI 契约 (bot.q.qq.com) 的成功判定。

    成功时 HTTP 2xx 直接返回业务数据 (群/C2C: {"id", "timestamp"} 消息对象;
    频道: Message 对象), 响应体**不含** code 字段; 失败时返回非 2xx 状态 +
    code/message (_http_post 对非 2xx 已返回 None)。此前实现按 `code == 0`
    判成功 —— 成功响应必然无 code → None → -1 → 所有真实成功发送被判失败;
    单测用虚构 {"code":0} 响应与实现互相印证 (与 Fix-37 企微 AES 布局错误同构)。
    现: 2xx + 无错误字段 → 成功; 若带 err_code/code 且非 0 → fail-closed
    (网关异常透传等未文档化形态保守拒绝)。
    """
    err_raw = resp.get("err_code")
    if err_raw is None:
        err_raw = resp.get("code")
    if err_raw is not None:
        try:
            err = int(err_raw)
        except (TypeError, ValueError):
            err = -1
        if err != 0:
            logger.warning("QQ 官方 send 返回错误码", code=err, msg=str(resp.get("message", "")))
            return False
    return True


def _derive_seed(secret: str) -> bytes:
    """从 bot_secret 派生 Ed25519 seed (字节序核对自 bot.q.qq.com 官方文档)。

    seed = secret 重复双倍直到 len >= 32, 取前 32 字节 UTF-8 编码。
    (与 Go ``strings.Repeat(seed, 2)`` 等价: 双倍而非相加)
    """
    s = secret or ""
    while len(s) < _ED25519_SEED_SIZE:
        s = s + s  # 双倍 (strings.Repeat(s, 2) 等价)
    return s[:_ED25519_SEED_SIZE].encode("utf-8")


def _strip_at_prefix(content: str) -> str:
    """剥离 @机器人 前缀 (QQ 官方事件 content 含 ``<@!bot_appid>`` 前缀)。"""
    import re

    return re.sub(r"^<@!\d+>\s*", "", content or "")
